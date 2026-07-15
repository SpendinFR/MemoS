"""Lossless, restartable SQLite evidence pagination for nightly stages.

The caller supplies an owner-scoped SELECT which exposes a stable primary key
as ``__page_pk``.  Pages are read by keyset (never OFFSET), hashed, and their
commit marker is written atomically with the optional transformed page result.
An existing committed page is reused only when its freshly-read input digest is
identical.  Therefore a crash after a page commit resumes safely, while a
changed source row invalidates the cached page.

Page size is strictly a memory/transaction boundary.  Completion is true only
when the number of included source rows equals the exact source query count.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from typing import Any, Callable, Mapping, Sequence

from ..db import write_transaction
from ..utils import json_dumps, json_loads, now_iso, stable_id
from .evidence_ref import content_digest


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS night_evidence_page_runs_v19(
  run_key TEXT PRIMARY KEY,
  stage_name TEXT NOT NULL,
  person_id TEXT NOT NULL,
  source_family TEXT NOT NULL,
  query_digest TEXT NOT NULL,
  page_size INTEGER NOT NULL,
  status TEXT NOT NULL,
  source_count INTEGER NOT NULL DEFAULT 0,
  included_count INTEGER NOT NULL DEFAULT 0,
  page_count INTEGER NOT NULL DEFAULT 0,
  first_pk TEXT,
  last_pk TEXT,
  digest TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS night_evidence_pages_v19(
  run_key TEXT NOT NULL,
  page_index INTEGER NOT NULL,
  first_pk TEXT NOT NULL,
  last_pk TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  input_digest TEXT NOT NULL,
  output_json TEXT,
  state_after_json TEXT,
  status TEXT NOT NULL,
  committed_at TEXT NOT NULL,
  PRIMARY KEY(run_key, page_index),
  FOREIGN KEY(run_key) REFERENCES night_evidence_page_runs_v19(run_key)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_night_evidence_page_family_v19
  ON night_evidence_page_runs_v19(person_id, stage_name, source_family, updated_at);
"""


class IncompleteEvidenceError(RuntimeError):
    """Raised instead of promoting a partially traversed source query."""


PageTransform = Callable[
    [list[dict[str, Any]], Any], tuple[Any, Any]
]
Failpoint = Callable[[str, Mapping[str, Any]], None]


@dataclass(frozen=True)
class PagedEvidenceResult:
    rows: list[dict[str, Any]]
    outputs: list[Any]
    final_state: Any
    manifest: dict[str, Any]


_SCHEMA_READY: set[str] = set()


def ensure_paged_evidence_schema(con: sqlite3.Connection) -> None:
    row = con.execute("PRAGMA database_list").fetchone()
    path = str(row[2] if row is not None else "")
    key = path or f":memory:{id(con)}"
    if key in _SCHEMA_READY:
        return
    con.executescript(SCHEMA)
    con.commit()
    _SCHEMA_READY.add(key)


def _query_without_trailing_semicolon(sql: str) -> str:
    text = str(sql or "").strip().rstrip(";").strip()
    if not text:
        raise ValueError("paged evidence query is empty")
    return text


def _clean_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(k): v for k, v in dict(row).items() if str(k) != "__page_pk"}


def _cached_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    return json_loads(value, default) if isinstance(value, str) else value


def read_query_pages(
    con: sqlite3.Connection,
    *,
    stage_name: str,
    person_id: str,
    source_family: str,
    select_sql: str,
    params: Sequence[Any] = (),
    page_size: int = 120,
    transform: PageTransform | None = None,
    initial_state: Any = None,
    collect_rows: bool = True,
    scope_key: str | None = None,
    failpoint: Failpoint | None = None,
) -> PagedEvidenceResult:
    """Read every row from ``select_sql`` through stable-key pages.

    ``select_sql`` must expose a unique, non-null text-compatible column named
    ``__page_pk`` and must not contain LIMIT/OFFSET.  Its own ordering is ignored;
    the wrapper applies ``ORDER BY CAST(__page_pk AS TEXT)`` consistently.

    A transform may return ``(page_output, state_after)``.  Both values are
    committed with the page marker, allowing a restart to reuse the completed
    transformation.  Raw rows are not copied into the journal unless the
    transform explicitly returns them.
    """

    ensure_paged_evidence_schema(con)
    if int(page_size) <= 0:
        raise ValueError("page_size must be positive")
    base = _query_without_trailing_semicolon(select_sql)
    bound = tuple(params)
    query_digest = content_digest({
        "sql": " ".join(base.split()),
        "params": list(bound),
        "scope_key": scope_key,
    })
    run_key = stable_id(
        "evidencepages", stage_name, person_id, source_family,
        query_digest, int(page_size),
    )
    now = now_iso()
    with write_transaction(con):
        con.execute(
            """INSERT INTO night_evidence_page_runs_v19(
                   run_key,stage_name,person_id,source_family,query_digest,
                   page_size,status,created_at,updated_at
               ) VALUES(?,?,?,?,?,?, 'reading', ?,?)
               ON CONFLICT(run_key) DO UPDATE SET
                   status='reading', updated_at=excluded.updated_at""",
            (
                run_key, stage_name, person_id, source_family, query_digest,
                int(page_size), now, now,
            ),
        )

    count_row = con.execute(
        f"SELECT COUNT(*) AS n FROM ({base}) AS source_rows",
        bound,
    ).fetchone()
    source_count = int(count_row["n"] if count_row is not None else 0)
    page_sql = (
        f"SELECT * FROM ({base}) AS source_rows "
        "WHERE CAST(__page_pk AS TEXT)>? "
        "ORDER BY CAST(__page_pk AS TEXT) LIMIT ?"
    )

    cursor = ""
    page_index = 0
    included_count = 0
    rows_out: list[dict[str, Any]] = []
    outputs: list[Any] = []
    state = initial_state
    page_digests: list[dict[str, Any]] = []
    first_pk: str | None = None
    last_pk: str | None = None

    while True:
        fetched = [dict(row) for row in con.execute(
            page_sql, (*bound, cursor, int(page_size))
        ).fetchall()]
        if not fetched:
            break
        pks = [str(row.get("__page_pk") or "") for row in fetched]
        if any(not pk for pk in pks) or len(set(pks)) != len(pks):
            raise IncompleteEvidenceError(
                f"{source_family}: __page_pk must be non-null and unique per page"
            )
        if any(pk <= cursor for pk in pks):
            raise IncompleteEvidenceError(
                f"{source_family}: unstable/non-monotonic page key after {cursor!r}"
            )
        clean_rows = [_clean_row(row) for row in fetched]
        input_digest = content_digest([
            {"pk": pk, "row": row} for pk, row in zip(pks, clean_rows)
        ])
        cached = con.execute(
            """SELECT * FROM night_evidence_pages_v19
               WHERE run_key=? AND page_index=? AND status='committed'""",
            (run_key, page_index),
        ).fetchone()
        can_reuse = bool(
            cached is not None
            and str(cached["input_digest"]) == input_digest
            and str(cached["first_pk"]) == pks[0]
            and str(cached["last_pk"]) == pks[-1]
            and int(cached["row_count"]) == len(clean_rows)
            and (transform is None or cached["output_json"] is not None)
        )
        if transform is None:
            output = None
            state_after = state
        elif can_reuse:
            output = _cached_json(cached["output_json"], None)
            state_after = _cached_json(cached["state_after_json"], state)
        else:
            output, state_after = transform(clean_rows, state)
            if failpoint:
                failpoint("after_transform_before_commit", {
                    "run_key": run_key, "page_index": page_index,
                    "first_pk": pks[0], "last_pk": pks[-1],
                })

        if not can_reuse:
            with write_transaction(con):
                con.execute(
                    """INSERT INTO night_evidence_pages_v19(
                           run_key,page_index,first_pk,last_pk,row_count,
                           input_digest,output_json,state_after_json,status,committed_at
                       ) VALUES(?,?,?,?,?,?,?,?, 'committed', ?)
                       ON CONFLICT(run_key,page_index) DO UPDATE SET
                           first_pk=excluded.first_pk,last_pk=excluded.last_pk,
                           row_count=excluded.row_count,input_digest=excluded.input_digest,
                           output_json=excluded.output_json,
                           state_after_json=excluded.state_after_json,
                           status='committed',committed_at=excluded.committed_at""",
                    (
                        run_key, page_index, pks[0], pks[-1], len(clean_rows),
                        input_digest,
                        json_dumps(output) if transform is not None else None,
                        json_dumps(state_after) if transform is not None else None,
                        now_iso(),
                    ),
                )
        if failpoint:
            failpoint("after_commit_before_next_page", {
                "run_key": run_key, "page_index": page_index,
                "reused": can_reuse,
            })

        if collect_rows:
            rows_out.extend(clean_rows)
        if transform is not None:
            outputs.append(output)
        state = state_after
        included_count += len(clean_rows)
        if first_pk is None:
            first_pk = pks[0]
        last_pk = pks[-1]
        cursor = pks[-1]
        page_digests.append({
            "page_index": page_index,
            "first_pk": pks[0],
            "last_pk": pks[-1],
            "row_count": len(clean_rows),
            "digest": input_digest,
        })
        page_index += 1
        if len(clean_rows) < int(page_size):
            break

    complete = included_count == source_count
    digest = content_digest(page_digests)
    status = "completed" if complete else "incomplete"
    with write_transaction(con):
        # A changed source can reduce its page count; stale suffix pages must not
        # be mistaken for proof of the current traversal.
        con.execute(
            "DELETE FROM night_evidence_pages_v19 WHERE run_key=? AND page_index>=?",
            (run_key, page_index),
        )
        con.execute(
            """UPDATE night_evidence_page_runs_v19 SET
                   status=?,source_count=?,included_count=?,page_count=?,
                   first_pk=?,last_pk=?,digest=?,updated_at=?
               WHERE run_key=?""",
            (
                status, source_count, included_count, page_index,
                first_pk, last_pk, digest, now_iso(), run_key,
            ),
        )
    manifest = {
        "run_key": run_key,
        "stage_name": stage_name,
        "source_family": source_family,
        "source_count": source_count,
        "included_count": included_count,
        "page_count": page_index,
        "page_size": int(page_size),
        "first_pk": first_pk,
        "last_pk": last_pk,
        "digest": digest,
        "complete": complete,
    }
    if not complete:
        raise IncompleteEvidenceError(
            f"{source_family}: included {included_count}/{source_count} rows"
        )
    return PagedEvidenceResult(
        rows=rows_out, outputs=outputs, final_state=state, manifest=manifest
    )


def table_select_sql(
    *, table: str, pk: str, where_sql: str = "1=1", columns: str = "*",
) -> str:
    """Build the common single-table SELECT after validating identifiers."""

    if not _IDENTIFIER.fullmatch(str(table)) or not _IDENTIFIER.fullmatch(str(pk)):
        raise ValueError("unsafe table or primary-key identifier")
    return (
        f"SELECT {columns}, {pk} AS __page_pk FROM {table} "
        f"WHERE ({where_sql})"
    )
