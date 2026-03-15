from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.contracts.context import normalize_token
from app.core.contracts.ids import new_record_id
from app.core.database.bootstrap import ensure_database

ALLOWED_ROLES = {"owner", "gm", "player"}
DEFAULT_ROLE = "player"
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1
PASSWORD_KEY_LEN = 32


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def normalize_role(role: Any) -> str:
    value = normalize_token(role) or DEFAULT_ROLE
    if value not in ALLOWED_ROLES:
        raise ValueError(f"unsupported role '{role}'")
    return value


def normalize_email(email: Any) -> str:
    value = str(email or "").strip().lower()
    if not value or "@" not in value:
        raise ValueError("valid email is required")
    return value


def hash_password(password: str) -> str:
    raw = str(password or "")
    if len(raw) < 8:
        raise ValueError("password must be at least 8 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        raw.encode("utf-8"),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=PASSWORD_KEY_LEN,
    )
    return (
        f"scrypt${PASSWORD_SCRYPT_N}${PASSWORD_SCRYPT_R}${PASSWORD_SCRYPT_P}"
        f"${salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, n_text, r_text, p_text, salt_hex, digest_hex = str(encoded_hash).split("$", 5)
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False
    try:
        n = int(n_text)
        r = int(r_text)
        p = int(p_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except Exception:
        return False
    candidate = hashlib.scrypt(
        str(password or "").encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=len(expected),
    )
    return hmac.compare_digest(candidate, expected)


@dataclass
class AuthUser:
    id: str
    username: str
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: str
    updated_at: str


@dataclass
class AuthSession:
    id: str
    user_id: str
    created_at: str
    expires_at: str
    revoked_at: str | None


class AuthService:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        ensure_database(self.db_path)

    def create_user(
        self,
        *,
        username: str,
        email: str,
        display_name: str,
        password: str,
        role: str = DEFAULT_ROLE,
    ) -> AuthUser:
        normalized_username = normalize_token(username)
        if not normalized_username:
            raise ValueError("username is required")
        clean_display = str(display_name or "").strip()
        if not clean_display:
            raise ValueError("display_name is required")
        normalized_email = normalize_email(email)
        normalized_role = normalize_role(role)
        password_hash = hash_password(password)

        user = AuthUser(
            id=new_record_id().replace("rec_", "usr_", 1),
            username=normalized_username,
            email=normalized_email,
            display_name=clean_display,
            role=normalized_role,
            is_active=True,
            created_at=_utc_now_iso(),
            updated_at=_utc_now_iso(),
        )
        conn = _connect(self.db_path)
        try:
            try:
                conn.execute(
                    """
                    INSERT INTO users(
                        id, username, email, display_name, role, password_hash, created_at, updated_at, is_active
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        user.id,
                        user.username,
                        user.email,
                        user.display_name,
                        user.role,
                        password_hash,
                        user.created_at,
                        user.updated_at,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"user already exists: {normalized_username}") from exc
        finally:
            conn.close()
        return user

    def get_user_by_username(self, username: str) -> AuthUser | None:
        normalized_username = normalize_token(username)
        if not normalized_username:
            return None
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT id, username, email, display_name, role, is_active, created_at, updated_at
                FROM users
                WHERE username = ?
                """,
                (normalized_username,),
            ).fetchone()
            return self._row_to_user(row)
        finally:
            conn.close()

    def authenticate(self, *, username: str, password: str) -> AuthUser | None:
        normalized_username = normalize_token(username)
        if not normalized_username:
            return None
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT id, username, email, display_name, role, password_hash, is_active, created_at, updated_at
                FROM users
                WHERE username = ?
                """,
                (normalized_username,),
            ).fetchone()
            if row is None or not bool(row["is_active"]):
                return None
            if not verify_password(password, str(row["password_hash"])):
                return None
            return self._row_to_user(row)
        finally:
            conn.close()

    def get_user_by_id(self, user_id: str) -> AuthUser | None:
        clean_id = str(user_id or "").strip()
        if not clean_id:
            return None
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT id, username, email, display_name, role, is_active, created_at, updated_at
                FROM users
                WHERE id = ?
                """,
                (clean_id,),
            ).fetchone()
            return self._row_to_user(row)
        finally:
            conn.close()

    def ensure_user(
        self,
        *,
        username: str,
        email: str,
        display_name: str,
        password: str,
        role: str = DEFAULT_ROLE,
    ) -> AuthUser:
        existing = self.get_user_by_username(username)
        if existing is not None:
            return existing
        return self.create_user(
            username=username,
            email=email,
            display_name=display_name,
            password=password,
            role=role,
        )

    def create_session(self, *, user_id: str, ttl_hours: int = 12) -> AuthSession:
        if not str(user_id or "").strip():
            raise ValueError("user_id is required")
        created_at = _utc_now()
        expires_at = created_at + timedelta(hours=max(1, int(ttl_hours or 1)))
        session = AuthSession(
            id=secrets.token_urlsafe(24),
            user_id=str(user_id).strip(),
            created_at=created_at.isoformat(),
            expires_at=expires_at.isoformat(),
            revoked_at=None,
        )
        conn = _connect(self.db_path)
        try:
            user_row = conn.execute(
                "SELECT id, is_active FROM users WHERE id = ?",
                (session.user_id,),
            ).fetchone()
            if user_row is None:
                raise ValueError(f"user not found: {session.user_id}")
            if not bool(user_row["is_active"]):
                raise ValueError(f"user is inactive: {session.user_id}")
            conn.execute(
                """
                INSERT INTO auth_sessions(id, user_id, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (
                    session.id,
                    session.user_id,
                    session.created_at,
                    session.expires_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return session

    def get_session(self, session_id: str) -> AuthSession | None:
        clean_id = str(session_id or "").strip()
        if not clean_id:
            return None
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT id, user_id, created_at, expires_at, revoked_at
                FROM auth_sessions
                WHERE id = ?
                """,
                (clean_id,),
            ).fetchone()
            if row is None:
                return None
            session = self._row_to_session(row)
            if session.revoked_at:
                return None
            if datetime.fromisoformat(session.expires_at) <= _utc_now():
                return None
            return session
        finally:
            conn.close()

    def revoke_session(self, session_id: str) -> dict[str, str]:
        clean_id = str(session_id or "").strip()
        if not clean_id:
            raise ValueError("session_id is required")
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT id, revoked_at FROM auth_sessions WHERE id = ?",
                (clean_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"session not found: {clean_id}")
            revoked_at = str(row["revoked_at"] or "").strip() or _utc_now_iso()
            conn.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE id = ?",
                (revoked_at, clean_id),
            )
            conn.commit()
            return {"id": clean_id, "revoked_at": revoked_at}
        finally:
            conn.close()

    def _row_to_user(self, row: sqlite3.Row | None) -> AuthUser | None:
        if row is None:
            return None
        return AuthUser(
            id=str(row["id"]),
            username=str(row["username"]),
            email=str(row["email"]),
            display_name=str(row["display_name"]),
            role=str(row["role"]),
            is_active=bool(row["is_active"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _row_to_session(self, row: sqlite3.Row | None) -> AuthSession | None:
        if row is None:
            return None
        return AuthSession(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            created_at=str(row["created_at"]),
            expires_at=str(row["expires_at"]),
            revoked_at=str(row["revoked_at"]) if row["revoked_at"] is not None else None,
        )
