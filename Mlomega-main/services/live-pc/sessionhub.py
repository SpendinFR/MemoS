from __future__ import annotations
import secrets, time, uuid
from threading import RLock
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

@dataclass
class ClockSample:
    client_send_ns: int
    server_recv_ns: int
    server_send_ns: int
    client_recv_ns: int
    offset_ns: int
    rtt_ns: int

@dataclass
class Session:
    session_id: str
    device_id: str
    token: str
    created_at_utc: str
    token_expires_at_utc: str
    _token_expires_monotonic: float = field(repr=False)
    clock_samples: list[ClockSample] = field(default_factory=list)

class SessionHub:
    def __init__(
        self,
        *,
        token_ttl_seconds: float = 600.0,
        renew_grace_seconds: float = 86400.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if token_ttl_seconds <= 0 or renew_grace_seconds < 0:
            raise ValueError("token TTL must be positive and renew grace non-negative")
        self.token_ttl_seconds = float(token_ttl_seconds)
        self.renew_grace_seconds = float(renew_grace_seconds)
        self._monotonic = monotonic
        self._lock = RLock()
        self._sessions: dict[str, Session] = {}
        self._tokens: dict[str, str] = {}
        self._expired_tokens: dict[str, tuple[str, float]] = {}

    def create_session(self, device_id: str) -> Session:
        with self._lock:
            self._purge_expired_locked()
            now = datetime.now(timezone.utc)
            stamp = now.strftime('%Y%m%dT%H%M%S.%fZ')
            session_id = f"xr-{stamp}-{uuid.uuid4()}"
            token = secrets.token_urlsafe(32)
            session = Session(
                session_id=session_id,
                device_id=device_id,
                token=token,
                created_at_utc=now.isoformat(),
                token_expires_at_utc=(now + timedelta(seconds=self.token_ttl_seconds)).isoformat(),
                _token_expires_monotonic=self._monotonic() + self.token_ttl_seconds,
            )
            self._sessions[session_id] = session
            self._tokens[token] = session_id
            return session

    def authenticate(self, token: str) -> Session | None:
        with self._lock:
            self._purge_expired_locked()
            sid = self._tokens.get(token)
            return self._sessions.get(sid) if sid else None

    def rotate_token(self, session: Session) -> str:
        with self._lock:
            self._purge_expired_locked()
            current = self._sessions.get(session.session_id)
            if current is not session:
                raise KeyError(session.session_id)
            old_token = session.token
            new_token = secrets.token_urlsafe(32)
            now = datetime.now(timezone.utc)
            session.token = new_token
            session.token_expires_at_utc = (
                now + timedelta(seconds=self.token_ttl_seconds)
            ).isoformat()
            session._token_expires_monotonic = self._monotonic() + self.token_ttl_seconds
            self._tokens.pop(old_token, None)
            self._expired_tokens.pop(old_token, None)
            self._tokens[new_token] = session.session_id
            return new_token

    def renew_token(self, session_id: str, token: str) -> Session | None:
        """Rotate an active token or an expired token still in renew-only grace."""
        with self._lock:
            self._purge_expired_locked()
            active_sid = self._tokens.get(token)
            expired = self._expired_tokens.get(token)
            candidate_sid = active_sid or (expired[0] if expired else None)
            if candidate_sid != session_id:
                return None
            session = self._sessions.get(session_id)
            if session is None or session.token != token:
                return None
            self.rotate_token(session)
            return session

    def _purge_expired_locked(self) -> int:
        now = self._monotonic()
        for sid, session in list(self._sessions.items()):
            if session._token_expires_monotonic > now:
                continue
            if self._tokens.pop(session.token, None) is not None:
                self._expired_tokens[session.token] = (
                    sid,
                    session._token_expires_monotonic + self.renew_grace_seconds,
                )
        retired = 0
        for token, (sid, retire_at) in list(self._expired_tokens.items()):
            if retire_at > now:
                continue
            self._expired_tokens.pop(token, None)
            session = self._sessions.get(sid)
            if session is not None and session.token == token:
                self._sessions.pop(sid, None)
                retired += 1
        return retired

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired_locked()

    @property
    def session_count(self) -> int:
        with self._lock:
            self._purge_expired_locked()
            return len(self._sessions)

    def begin_clock_sync(self) -> int:
        return time.monotonic_ns()

    def complete_clock_sync(self, session_id: str, client_send_ns: int, server_recv_ns: int, client_recv_ns: int, server_send_ns: int | None = None) -> ClockSample:
        if session_id not in self._sessions:
            raise KeyError(session_id)
        server_send_ns = server_recv_ns if server_send_ns is None else server_send_ns
        rtt_ns = (client_recv_ns - client_send_ns) - (server_send_ns - server_recv_ns)
        offset_ns = ((server_recv_ns - client_send_ns) + (server_send_ns - client_recv_ns)) // 2
        sample = ClockSample(client_send_ns, server_recv_ns, server_send_ns, client_recv_ns, offset_ns, rtt_ns)
        self._sessions[session_id].clock_samples.append(sample)
        return sample

    def current_offset_ns(self, session_id: str) -> int | None:
        samples = self._sessions[session_id].clock_samples
        if not samples:
            return None
        best = min(samples, key=lambda s: s.rtt_ns)
        return best.offset_ns
