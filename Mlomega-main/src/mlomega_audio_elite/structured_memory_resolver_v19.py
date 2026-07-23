from __future__ import annotations

"""Deterministic live resolvers for exact memory questions.

The LLM remains useful for synthesis, but dates, counts, latest rows and replay
anchors are SQL facts.  This module resolves those facts first and returns a
small, evidenced answer packet that the live MemoryQuery can display directly.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import unicodedata
from typing import Any, Callable, Iterable


_MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _extract_civil_date(text: str) -> date | None:
    numeric = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text)
    if numeric:
        day, month, year = (int(part) for part in numeric.groups())
    else:
        named = re.search(
            r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})\b",
            _fold(text),
        )
        if not named:
            return None
        day = int(named.group(1))
        month = _MONTHS[named.group(2)]
        year = int(named.group(3))
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _iso_date(value: Any) -> str:
    return str(value or "")[:10]


def _human_date(value: Any) -> str:
    raw = _iso_date(value)
    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        return raw


def _tokens(value: str) -> set[str]:
    ignored = {
        "avec", "dans", "genre", "truc", "cette", "avait", "avais", "propos",
        "deux", "semaines", "semaine", "parlais", "parle", "quoi", "quel",
    }
    return {
        token for token in re.findall(r"[a-z0-9]{3,}", _fold(value))
        if token not in ignored
    }


@dataclass(frozen=True)
class StructuredAnswer:
    text: str
    evidence_refs: tuple[str, ...]
    kind: str
    truth_level: str = "remembered"
    confidence: float = 0.9
    title: str = "Mémoire"
    data: dict[str, Any] | None = None

    def packet(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "evidence_refs": list(self.evidence_refs),
            "kind": self.kind,
            "truth_level": self.truth_level,
            "confidence": self.confidence,
            "title": self.title,
            "data": dict(self.data or {}),
        }


class StructuredMemoryResolver:
    """Answer exact recurring memory questions without an LLM round-trip."""

    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        person_id: str = "me",
        replay_service: Any = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = Path(
            db_path or os.environ.get("MLOMEGA_DB") or "storage/memory.db"
        ).resolve()
        self.person_id = person_id or "me"
        self.replay_service = replay_service
        self._now = now_fn or (lambda: datetime.now(timezone.utc))

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(
            f"file:{self.db_path.as_posix()}?mode=ro", uri=True, timeout=2.0
        )
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _has_table(con: sqlite3.Connection, table: str) -> bool:
        return con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None

    def _people(self, con: sqlite3.Connection) -> list[tuple[str, str, set[str]]]:
        if not self._has_table(con, "speaker_profiles"):
            return []
        people = []
        for row in con.execute(
            "SELECT person_id,display_name,aliases_json FROM speaker_profiles"
        ):
            aliases = {
                _fold(alias) for alias in (_loads(row["aliases_json"], []) or [])
                if alias
            }
            aliases.add(_fold(row["display_name"]))
            aliases.add(_fold(row["person_id"]))
            people.append((str(row["person_id"]), str(row["display_name"]), aliases))
        return people

    def _person_in_question(
        self, con: sqlite3.Connection, question: str
    ) -> tuple[str, str] | None:
        folded = _fold(question)
        matches = [
            (pid, name) for pid, name, aliases in self._people(con)
            if any(alias and re.search(rf"\b{re.escape(alias)}\b", folded) for alias in aliases)
            and pid != self.person_id
        ]
        return matches[0] if matches else None

    @staticmethod
    def _conversation_has_person(row: sqlite3.Row, person_id: str, name: str) -> bool:
        haystack = _fold(
            " ".join([
                str(row["participants_json"] or ""),
                str(row["speaker_map_json"] or ""),
                str(row["relationship_context_json"] or ""),
            ])
        )
        return _fold(person_id) in haystack or _fold(name) in haystack

    def resolve(self, question: str) -> dict[str, Any] | None:
        question = (question or "").strip()
        if not question or not self.db_path.exists():
            return None
        q = _fold(question)
        try:
            with self._connect() as con:
                person = self._person_in_question(con, question)
                if (
                    ("ou" in q.split() or "endroit" in q)
                    and _extract_civil_date(question) is not None
                ):
                    return self._where_on_date(con, question)
                if person and ("derniere fois" in q or "derniere conversation" in q):
                    return self._last_encounter(con, *person)
                if person and ("combien de fois" in q or "position a evolue" in q):
                    return self._topic_history(con, question, *person)
                if person and any(word in q for word in ("embrouill", "conflit", "disput")):
                    return self._conflict_evidence(con, question, *person)
                if "prix" in q or "combien cout" in q:
                    return self._latest_attribute(con, question)
                if "predit" in q or "prediction" in q:
                    return self._predictions(con)
                if "expression" in q and any(word in q for word in ("favorite", "preferee", "moment")):
                    return self._favorite_expression(con)
                if person and ("deux semaines" in q or "y a genre" in q or "il y a genre" in q):
                    return self._fuzzy_episode(con, question, *person)
                if any(term in q for term in ("comment j ai reussi", "comment ai je reussi")):
                    return self._success_path(con, question)
                if any(term in q for term in ("rejoue", "replay", "revois")):
                    return self._semantic_replay(con, question, person)
        except sqlite3.Error:
            return None
        return None

    def _where_on_date(
        self, con: sqlite3.Connection, question: str
    ) -> dict[str, Any] | None:
        civil_date = _extract_civil_date(question)
        if civil_date is None or not self._has_table(con, "scene_session_summaries_v19"):
            return None
        target_date = civil_date.isoformat()
        date = target_date  # legacy local name retained for response formatting
        rows = con.execute(
            """SELECT scene_summary_id,summary_start,summary_end,place_hint,summary_json
               FROM scene_session_summaries_v19
               WHERE person_id=? AND substr(summary_start,1,10)=?
               ORDER BY summary_start""",
            (self.person_id, target_date),
        ).fetchall()
        if not rows:
            return StructuredAnswer(
                f"Je n’ai aucune localisation suffisamment fiable pour le {_human_date(date)}.",
                (), "temporal_spatial", "unknown", 0.0,
            ).packet()
        periods = []
        refs = []
        for row in rows:
            hour = str(row["summary_start"] or "")[11:16]
            place = str(row["place_hint"] or "").strip()
            if not place:
                summary = _loads(row["summary_json"], {}) or {}
                place = str(summary.get("place_hint") or summary.get("zone") or "lieu non nommé")
            period = "matin" if hour and hour < "12:00" else "après-midi" if hour < "18:00" else "soir"
            periods.append(f"{period} : {place}")
            refs.append(f"scene_session_summaries_v19:{row['scene_summary_id']}")
        return StructuredAnswer(
            f"Le {_human_date(date)}, " + "; ".join(dict.fromkeys(periods)) + ".",
            tuple(refs), "temporal_spatial", data={"date": date, "periods": periods},
        ).packet()

    def _person_conversations(
        self, con: sqlite3.Connection, person_id: str, name: str
    ) -> list[sqlite3.Row]:
        if not self._has_table(con, "conversations"):
            return []
        rows = con.execute(
            "SELECT * FROM conversations ORDER BY COALESCE(ended_at,started_at) DESC"
        ).fetchall()
        matched = []
        for row in rows:
            in_meta = self._conversation_has_person(row, person_id, name)
            in_turn = con.execute(
                """SELECT 1 FROM turns WHERE conversation_id=?
                   AND (person_id=? OR lower(speaker_label)=lower(?)) LIMIT 1""",
                (row["conversation_id"], person_id, name),
            ).fetchone()
            if in_meta or in_turn:
                matched.append(row)
        return matched

    def _last_encounter(
        self, con: sqlite3.Connection, person_id: str, name: str
    ) -> dict[str, Any] | None:
        rows = self._person_conversations(con, person_id, name)
        if not rows:
            return None
        conv = rows[0]
        cid = str(conv["conversation_id"])
        summary_row = None
        if self._has_table(con, "conversation_discourse_maps"):
            summary_row = con.execute(
                """SELECT discourse_id,conversation_summary FROM conversation_discourse_maps
                   WHERE conversation_id=? ORDER BY created_at DESC LIMIT 1""", (cid,)
            ).fetchone()
        turns = con.execute(
            """SELECT turn_id,speaker_label,person_id,text FROM turns
               WHERE conversation_id=? ORDER BY idx""", (cid,)
        ).fetchall()
        summary = (
            str(summary_row["conversation_summary"]) if summary_row
            else " ".join(str(row["text"]) for row in turns[-8:])
        )
        refs = [f"conversation:{cid}"]
        refs.extend(f"turn:{row['turn_id']}" for row in turns[-8:])
        if summary_row:
            refs.append(f"conversation_discourse_maps:{summary_row['discourse_id']}")
        return StructuredAnswer(
            f"La dernière fois avec {name} ({_human_date(conv['started_at'])}) : {summary}",
            tuple(refs), "last_encounter",
            data={"conversation_id": cid, "person_id": person_id},
        ).packet()

    def _topic_history(
        self, con: sqlite3.Connection, question: str, person_id: str, name: str
    ) -> dict[str, Any] | None:
        question_terms = _tokens(question) - _tokens(name)
        candidates = []
        for conv in self._person_conversations(con, person_id, name):
            turns = con.execute(
                """SELECT turn_id,text,person_id,speaker_label FROM turns
                   WHERE conversation_id=? ORDER BY idx""", (conv["conversation_id"],)
            ).fetchall()
            other = [
                row for row in turns
                if str(row["person_id"] or "") == person_id
                or _fold(row["speaker_label"]) == _fold(name)
            ]
            score = sum(
                len(question_terms & _tokens(str(row["text"]))) for row in other
            )
            if score:
                candidates.append((conv, other, score))
        if not candidates:
            return None
        candidates.sort(key=lambda item: str(item[0]["started_at"] or ""))
        latest_conv, latest_turns, _ = candidates[-1]
        latest_quote = str(latest_turns[-1]["text"])
        refs = [
            f"conversation:{item[0]['conversation_id']}" for item in candidates
        ] + [f"turn:{row['turn_id']}" for row in latest_turns]
        first_quote = str(candidates[0][1][0]["text"])
        evolution = (
            f"Au début : « {first_quote} ». Dernière position : « {latest_quote} »."
            if first_quote != latest_quote else f"Sa position est restée : « {latest_quote} »."
        )
        return StructuredAnswer(
            f"{name} a abordé ce sujet dans {len(candidates)} conversation(s). {evolution}",
            tuple(refs), "topic_history",
            data={"count": len(candidates), "person_id": person_id},
        ).packet()

    def _conflict_evidence(
        self, con: sqlite3.Connection, question: str, person_id: str, name: str
    ) -> dict[str, Any] | None:
        target_date = (self._now() - timedelta(days=1)).date().isoformat()
        conversations = [
            row for row in self._person_conversations(con, person_id, name)
            if _iso_date(row["started_at"]) == target_date
        ]
        if not conversations:
            return None
        conv = conversations[0]
        cid = str(conv["conversation_id"])
        turns = con.execute(
            "SELECT turn_id,text FROM turns WHERE conversation_id=? ORDER BY idx", (cid,)
        ).fetchall()
        observed = [str(row["text"]) for row in turns]
        refs = [f"turn:{row['turn_id']}" for row in turns]
        hypotheses = []
        if self._has_table(con, "conversation_turning_points"):
            for row in con.execute(
                """SELECT turning_point_id,summary,evidence_text FROM conversation_turning_points
                   WHERE conversation_id=? ORDER BY turn_idx""", (cid,)
            ):
                hypotheses.append(str(row["summary"]))
                refs.append(f"conversation_turning_points:{row['turning_point_id']}")
        if self._has_table(con, "causal_hypotheses"):
            for row in con.execute(
                """SELECT hypothesis_id,hypothesis_text,confidence FROM causal_hypotheses
                   WHERE person_id=? AND status IN ('candidate','confirmed')
                   ORDER BY confidence DESC LIMIT 3""", (self.person_id,)
            ):
                hypotheses.append(str(row["hypothesis_text"]))
                refs.append(f"causal_hypotheses:{row['hypothesis_id']}")
        text = (
            f"Observé : {' '.join(observed[-5:])} "
            + (
                f"Hypothèse appuyée par les signaux : {'; '.join(hypotheses[:3])}"
                if hypotheses else
                "Je n’ai pas assez de preuves pour attribuer une cause."
            )
        )
        return StructuredAnswer(
            text, tuple(refs), "conflict_evidence",
            truth_level="inferred" if hypotheses else "remembered",
            confidence=0.72 if hypotheses else 0.55,
            data={"facts": observed, "hypotheses": hypotheses},
        ).packet()

    def _latest_attribute(
        self, con: sqlite3.Connection, question: str
    ) -> dict[str, Any] | None:
        if not self._has_table(con, "attribute_memory_observations"):
            return None
        terms = _tokens(question)
        rows = con.execute(
            """SELECT * FROM attribute_memory_observations
               WHERE person_id=? ORDER BY observed_at DESC,obs_id DESC LIMIT 200""",
            (self.person_id,),
        ).fetchall()
        scored = []
        for row in rows:
            hay = _tokens(
                f"{row['subject']} {row['attribute']} {row['value']}"
            )
            score = len(terms & hay)
            if score or any(k in _fold(row["attribute"]) for k in ("prix", "price", "tarif")):
                scored.append((score, row))
        if not scored:
            return None
        scored.sort(key=lambda item: (item[0], str(item[1]["observed_at"])), reverse=True)
        row = scored[0][1]
        return StructuredAnswer(
            f"La dernière valeur observée le {_human_date(row['observed_at'])} : "
            f"{row['value']} ({row['source']}).",
            (f"attribute_memory_observations:{row['obs_id']}",),
            "latest_attribute",
            data=dict(row),
        ).packet()

    def _predictions(self, con: sqlite3.Connection) -> dict[str, Any] | None:
        rows: list[sqlite3.Row] = []
        source_table = "predictions"
        if self._has_table(con, "predictions_v19"):
            rows = con.execute(
                """SELECT * FROM predictions_v19 WHERE person_id=? AND status='open'
                   ORDER BY confidence DESC LIMIT 8""", (self.person_id,)
            ).fetchall()
            source_table = "predictions_v19"
        if not rows and self._has_table(con, "predictions"):
            rows = con.execute(
                """SELECT * FROM predictions WHERE person_id=? AND status='open'
                   ORDER BY confidence DESC LIMIT 8""", (self.person_id,)
            ).fetchall()
        if not rows:
            return StructuredAnswer(
                "Je n’ai pas encore assez de répétitions indépendantes pour une prédiction fiable.",
                (), "predictions", "unknown", 0.0,
            ).packet()
        parts, refs = [], []
        for row in rows:
            data = dict(row)
            prediction = (
                data.get("prediction_text") or data.get("statement")
                or data.get("predicted_value")
                or data.get("summary") or data.get("prediction_target")
            )
            horizon = data.get("horizon") or data.get("horizon_end") or "prochainement"
            confidence = float(data.get("confidence") or data.get("probability") or 0.0)
            if confidence < 0.6:
                continue
            parts.append(f"{horizon} : {prediction} (confiance {confidence:.0%})")
            refs.append(f"{source_table}:{data.get('prediction_id')}")
        if not parts:
            return StructuredAnswer(
                "Les signaux existent mais restent sous le seuil prudent de prédiction.",
                (), "predictions", "unknown", 0.0,
            ).packet()
        return StructuredAnswer(
            "Prévisions fondées sur les boucles observées : " + "; ".join(parts),
            tuple(refs), "predictions", "inferred", 0.7,
        ).packet()

    def _favorite_expression(self, con: sqlite3.Connection) -> dict[str, Any] | None:
        if not self._has_table(con, "personal_language_patterns"):
            return None
        row = con.execute(
            """SELECT * FROM personal_language_patterns
               WHERE person_id=? ORDER BY frequency DESC,last_seen DESC LIMIT 1""",
            (self.person_id,),
        ).fetchone()
        if not row:
            return None
        return StructuredAnswer(
            f"Ton expression la plus fréquente du moment est « {row['expression']} » "
            f"({row['frequency']} occurrences, dernière le {_human_date(row['last_seen'])}).",
            (f"personal_language_patterns:{row['language_pattern_id']}",),
            "current_language",
            data={"expression": row["expression"], "frequency": row["frequency"]},
        ).packet()

    def _fuzzy_episode(
        self, con: sqlite3.Connection, question: str, person_id: str, name: str
    ) -> dict[str, Any] | None:
        center = (self._now() - timedelta(days=14)).date()
        terms = _tokens(question) - _tokens(name)
        matches = []
        for conv in self._person_conversations(con, person_id, name):
            try:
                day = datetime.fromisoformat(str(conv["started_at"])[:10]).date()
            except ValueError:
                continue
            if abs((day - center).days) > 5:
                continue
            turns = con.execute(
                "SELECT turn_id,text FROM turns WHERE conversation_id=? ORDER BY idx",
                (conv["conversation_id"],),
            ).fetchall()
            text = " ".join(str(row["text"]) for row in turns)
            score = len(terms & _tokens(text))
            matches.append((score, conv, turns))
        matches.sort(key=lambda item: item[0], reverse=True)
        if not matches:
            return None
        if len(matches) > 1 and matches[0][0] == matches[1][0]:
            options = [
                f"{_human_date(item[1]['started_at'])}: {item[1]['topic'] or item[1]['title']}"
                for item in matches[:3]
            ]
            return StructuredAnswer(
                "J’ai plusieurs scènes possibles : " + "; ".join(options)
                + ". Précise laquelle.",
                tuple(f"conversation:{item[1]['conversation_id']}" for item in matches[:3]),
                "fuzzy_episode", "unknown", 0.4,
                data={"needs_clarification": True, "options": options},
            ).packet()
        _, conv, turns = matches[0]
        summary = " ".join(str(row["text"]) for row in turns[-6:])
        return StructuredAnswer(
            f"Je pense à la conversation du {_human_date(conv['started_at'])} avec {name} : {summary}",
            tuple([f"conversation:{conv['conversation_id']}"] + [
                f"turn:{row['turn_id']}" for row in turns[-6:]
            ]),
            "fuzzy_episode", "remembered", 0.75,
        ).packet()

    def _success_path(
        self, con: sqlite3.Connection, question: str
    ) -> dict[str, Any] | None:
        if not self._has_table(con, "action_outcomes"):
            return None
        outcome = con.execute(
            """SELECT * FROM action_outcomes WHERE person_id=?
               AND COALESCE(success_level,0)>=0.6
               ORDER BY updated_at DESC LIMIT 1""", (self.person_id,)
        ).fetchone()
        if not outcome:
            return None
        episode = None
        choice = None
        if outcome["episode_id"] and self._has_table(con, "episodes"):
            episode = con.execute(
                "SELECT * FROM episodes WHERE episode_id=?", (outcome["episode_id"],)
            ).fetchone()
        if self._has_table(con, "choice_episodes"):
            choice = con.execute(
                """SELECT * FROM choice_episodes
                   WHERE person_id=? AND (outcome_id=? OR episode_id=?)
                   ORDER BY updated_at DESC LIMIT 1""",
                (self.person_id, outcome["outcome_id"], outcome["episode_id"]),
            ).fetchone()
        pieces = []
        refs = [f"action_outcomes:{outcome['outcome_id']}"]
        if episode:
            pieces.append(f"contexte : {episode['situation_summary']}")
            refs.append(f"episode:{episode['episode_id']}")
        if choice:
            pieces.append(
                f"choix : {choice['chosen_option']} ({choice['reason_given'] or 'raison non explicitée'})"
            )
            refs.append(f"choice_episodes:{choice['choice_id']}")
        pieces.append(f"action : {outcome['action_taken']}")
        pieces.append(f"résultat : {outcome['result']}")
        if outcome["lesson"]:
            pieces.append(f"leçon observée : {outcome['lesson']}")
        return StructuredAnswer(
            "Tu as réussi par cette chaîne vérifiable — " + "; ".join(pieces) + ".",
            tuple(refs), "success_path", "inferred", 0.78,
        ).packet()

    def _semantic_replay(
        self,
        con: sqlite3.Connection,
        question: str,
        person: tuple[str, str] | None,
    ) -> dict[str, Any] | None:
        if self.replay_service is None:
            return None
        terms = _tokens(question)
        candidates = []
        allowed_conversations: set[str] | None = None
        if person is not None:
            allowed_conversations = {
                str(row["conversation_id"])
                for row in self._person_conversations(con, person[0], person[1])
            }
        sql = (
            """SELECT t.turn_id,t.text,c.conversation_id,c.started_at
               FROM turns t JOIN conversations c ON c.conversation_id=t.conversation_id
               ORDER BY c.started_at DESC,t.idx DESC LIMIT 1000"""
        )
        for row in con.execute(sql):
            if (
                allowed_conversations is not None
                and str(row["conversation_id"]) not in allowed_conversations
            ):
                continue
            score = len(terms & _tokens(str(row["text"])))
            if score:
                candidates.append((score, row))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        row = candidates[0][1]
        try:
            dt = datetime.fromisoformat(str(row["started_at"]).replace("Z", "+00:00"))
        except ValueError:
            return None
        result = self.replay_service.replay(
            time=f"{dt.hour:02d}h{dt.minute:02d}", date=dt.date().isoformat()
        )
        if result.get("status") != "ok":
            return None
        virtual_screen = dict(result.get("virtual_screen") or {})
        turn_ref = f"turn:{row['turn_id']}"
        virtual_screen["evidence_refs"] = list(dict.fromkeys([
            *(virtual_screen.get("evidence_refs") or []),
            turn_ref,
        ]))
        # MemoryQuery accepts a ready UI intent packet as well as a text packet.
        return {
            "ui_intent": virtual_screen,
            "companion_intent": result.get("timeline"),
            "kind": "semantic_replay",
            "evidence_refs": [turn_ref],
        }
