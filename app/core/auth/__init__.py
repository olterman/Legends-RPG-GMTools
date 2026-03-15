"""Core auth package."""

from .service import (
    ALLOWED_ROLES,
    DEFAULT_ROLE,
    AuthService,
    AuthSession,
    AuthUser,
    hash_password,
    normalize_email,
    normalize_role,
    verify_password,
)

__all__ = [
    "ALLOWED_ROLES",
    "DEFAULT_ROLE",
    "AuthService",
    "AuthSession",
    "AuthUser",
    "hash_password",
    "normalize_email",
    "normalize_role",
    "verify_password",
]
