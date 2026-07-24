"""
src/core/user_service.py
~~~~~~~~~~~~~~~~~~~~~~~~
Service layer for all user, character, and subscription CRUD operations.

All Supabase reads/writes are centralised here — the Streamlit UI and
PaymentVerifier never touch the database directly.

Data model (mirrors Supabase schema):
  User          — one row per EVE login character (primary identity)
  Character     — each linked EVE character (includes primary)
  Subscription  — one active paid subscription per user
  Payment       — audit log of verified ISK deposits
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from src.config import ADMIN_CHARACTER_ID, TIER_CHAR_LIMITS


# ---------------------------------------------------------------------------
# Admin helper
# ---------------------------------------------------------------------------

def is_admin(user: "User") -> bool:
    """
    Return True if this user is the app owner (admin).

    The check is purely in-memory — admin status is never stored in Supabase.
    Returns False unconditionally when ADMIN_CHARACTER_ID is 0 (disabled).
    """
    return ADMIN_CHARACTER_ID != 0 and user.character_id == ADMIN_CHARACTER_ID


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CharacterLimitError(Exception):
    """Raised when a user tries to add a character beyond their tier limit."""

    def __init__(self, current: int, limit: int, tier: str) -> None:
        self.current = current
        self.limit = limit
        self.tier = tier
        super().__init__(
            f"Character limit reached ({current}/{limit}) for tier '{tier}'. "
            "Upgrade to add more characters."
        )


# ---------------------------------------------------------------------------
# Typed data containers
# ---------------------------------------------------------------------------

@dataclass
class User:
    id: str                       # UUID
    character_id: int             # primary EVE character ID
    character_name: str
    tier: str                     # 'free' | 'premium' | 'corporate'
    tier_char_limit: int          # 2 | 10 | 9999 (None stored as 9999 for SQL compat)
    created_at: str


@dataclass
class Character:
    id: str                       # UUID
    user_id: str
    character_id: int
    character_name: str
    is_primary: bool
    access_token: str | None
    refresh_token: str | None
    token_expiry: float | None
    accounting_level: int
    broker_level: int
    last_synced: str | None
    added_at: str


@dataclass
class Subscription:
    id: str
    user_id: str
    tier: str
    starts_at: str
    expires_at: str
    is_active: bool
    renewed_count: int

    @property
    def days_remaining(self) -> int:
        """Return whole days until the subscription expires (0 if expired)."""
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        delta = expiry - datetime.now(timezone.utc)
        return max(0, delta.days)


@dataclass
class Payment:
    id: str
    user_id: str
    character_id: int
    character_name: str
    amount_isk: int
    tier_granted: str
    esi_journal_id: int
    verified_at: str


# ---------------------------------------------------------------------------
# UserService
# ---------------------------------------------------------------------------

class UserService:
    """
    All user/character/subscription database operations.

    Args:
        db: Admin Supabase client (from get_admin_db()).
    """

    # Corporate tier is stored as 9999 in the DB so the column stays INT.
    _CORPORATE_LIMIT_SENTINEL = 9999

    def __init__(self, db: Any) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def get_or_create_user(self, character_id: int, character_name: str) -> User:
        """
        Return the user row for this EVE character, creating one if it doesn't exist.

        Also creates the primary Character row if the user is new.
        """
        result = (
            self._db.table("users")
            .select("*")
            .eq("character_id", character_id)
            .execute()
        )

        if result.data:
            row = result.data[0]
            return self._user_from_row(row)

        # New user — insert with free tier defaults
        new_user = (
            self._db.table("users")
            .insert({
                "character_id":     character_id,
                "character_name":   character_name,
                "tier":             "free",
                "tier_char_limit":  TIER_CHAR_LIMITS["free"],
            })
            .execute()
        )
        user = self._user_from_row(new_user.data[0])

        # Insert the primary character row
        self._db.table("characters").insert({
            "user_id":        user.id,
            "character_id":   character_id,
            "character_name": character_name,
            "is_primary":     True,
        }).execute()

        return user

    def get_user_by_id(self, user_id: str) -> User | None:
        """Return a user by their Supabase UUID, or None if not found."""
        result = (
            self._db.table("users")
            .select("*")
            .eq("id", user_id)
            .execute()
        )
        if not result.data:
            return None
        return self._user_from_row(result.data[0])

    # ------------------------------------------------------------------
    # Characters
    # ------------------------------------------------------------------

    def get_characters(self, user_id: str) -> list[Character]:
        """Return all characters linked to a user, primary first."""
        result = (
            self._db.table("characters")
            .select("*")
            .eq("user_id", user_id)
            .order("is_primary", desc=True)
            .order("added_at")
            .execute()
        )
        return [self._character_from_row(r) for r in result.data]

    def get_character(self, character_id: int) -> Character | None:
        """Return a single character row by EVE character ID."""
        result = (
            self._db.table("characters")
            .select("*")
            .eq("character_id", character_id)
            .execute()
        )
        if not result.data:
            return None
        return self._character_from_row(result.data[0])

    def add_character(
        self,
        user_id: str,
        character_id: int,
        character_name: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_expiry: float | None = None,
    ) -> Character:
        """
        Link a new alt character to the user's account.

        Raises CharacterLimitError if the user is already at their tier limit.
        Raises ValueError if the character is already linked.
        """
        user = self.get_user_by_id(user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found.")

        current_chars = self.get_characters(user_id)

        # Enforce tier limit (corporate = 9999 = effectively unlimited)
        limit = user.tier_char_limit
        if limit < self._CORPORATE_LIMIT_SENTINEL and len(current_chars) >= limit:
            raise CharacterLimitError(
                current=len(current_chars),
                limit=limit,
                tier=user.tier,
            )

        # Check for duplicate
        if any(c.character_id == character_id for c in current_chars):
            raise ValueError(f"Character {character_id} is already linked to this account.")

        result = (
            self._db.table("characters")
            .insert({
                "user_id":        user_id,
                "character_id":   character_id,
                "character_name": character_name,
                "is_primary":     False,
                "access_token":   access_token,
                "refresh_token":  refresh_token,
                "token_expiry":   token_expiry,
            })
            .execute()
        )
        return self._character_from_row(result.data[0])

    def remove_character(self, user_id: str, character_id: int) -> None:
        """
        Remove an alt character from the user's account.

        Raises ValueError if attempting to remove the primary character.
        """
        char = self.get_character(character_id)
        if char is None:
            return  # already gone, idempotent
        if char.is_primary:
            raise ValueError("Cannot remove the primary login character.")
        self._db.table("characters").delete().eq("character_id", character_id).eq("user_id", user_id).execute()

    def update_character_tokens(
        self,
        character_id: int,
        access_token: str,
        refresh_token: str,
        token_expiry: float,
    ) -> None:
        """Persist refreshed ESI tokens for a character back to Supabase."""
        self._db.table("characters").update({
            "access_token":  access_token,
            "refresh_token": refresh_token,
            "token_expiry":  token_expiry,
        }).eq("character_id", character_id).execute()

    def update_character_skills(
        self,
        character_id: int,
        accounting_level: int,
        broker_level: int,
    ) -> None:
        """Cache a character's skill levels after a fresh ESI fetch."""
        self._db.table("characters").update({
            "accounting_level": accounting_level,
            "broker_level":     broker_level,
            "last_synced":      datetime.now(timezone.utc).isoformat(),
        }).eq("character_id", character_id).execute()

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def get_active_subscription(self, user_id: str) -> Subscription | None:
        """Return the user's active paid subscription, or None."""
        result = (
            self._db.table("subscriptions")
            .select("*")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .order("starts_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return self._subscription_from_row(result.data[0])

    def grant_subscription(
        self,
        user_id: str,
        tier: str,
        payment: dict[str, Any],
    ) -> Subscription:
        """
        Grant a paid subscription to a user and record the payment.

        Args:
            user_id: Supabase user UUID.
            tier:    'premium' or 'corporate'.
            payment: Dict with keys: character_id, character_name,
                     amount_isk, esi_journal_id.

        Returns the new Subscription record.
        """
        limit = TIER_CHAR_LIMITS.get(tier)
        db_limit = limit if limit is not None else self._CORPORATE_LIMIT_SENTINEL

        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=365)

        # Deactivate any existing subscription
        self._db.table("subscriptions").update({"is_active": False}).eq("user_id", user_id).eq("is_active", True).execute()

        # Create new subscription
        sub_result = (
            self._db.table("subscriptions")
            .insert({
                "user_id":    user_id,
                "tier":       tier,
                "starts_at":  now.isoformat(),
                "expires_at": expires.isoformat(),
                "is_active":  True,
            })
            .execute()
        )
        sub = self._subscription_from_row(sub_result.data[0])

        # Update user tier + char limit
        self._db.table("users").update({
            "tier":            tier,
            "tier_char_limit": db_limit,
        }).eq("id", user_id).execute()

        # Record payment for audit
        self._db.table("payments").insert({
            "user_id":        user_id,
            "character_id":   payment["character_id"],
            "character_name": payment["character_name"],
            "amount_isk":     payment["amount_isk"],
            "tier_granted":   tier,
            "esi_journal_id": payment["esi_journal_id"],
        }).execute()

        return sub

    def expire_subscriptions(self) -> int:
        """
        Mark all subscriptions whose expires_at has passed as inactive.
        Also resets the user's tier back to 'free'.

        The admin user (ADMIN_CHARACTER_ID) is always skipped — their tier
        is an in-memory overlay and should never be touched here.

        Returns the number of subscriptions expired.
        """
        now = datetime.now(timezone.utc).isoformat()

        expired = (
            self._db.table("subscriptions")
            .select("id, user_id")
            .eq("is_active", True)
            .lt("expires_at", now)
            .execute()
        )

        # Resolve admin user_id once so we can skip their row cheaply
        _admin_user_id: str | None = None
        if ADMIN_CHARACTER_ID != 0:
            res = (
                self._db.table("users")
                .select("id")
                .eq("character_id", ADMIN_CHARACTER_ID)
                .execute()
            )
            if res.data:
                _admin_user_id = res.data[0]["id"]

        count = 0
        for row in expired.data:
            if row["user_id"] == _admin_user_id:
                continue  # never downgrade the admin
            self._db.table("subscriptions").update({"is_active": False}).eq("id", row["id"]).execute()
            self._db.table("users").update({
                "tier":            "free",
                "tier_char_limit": TIER_CHAR_LIMITS["free"],
            }).eq("id", row["user_id"]).execute()
            count += 1

        return count

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def create_session(self, user_id: str, ttl_hours: int = 24) -> str:
        """
        Create a new session token for the user and persist it.

        Returns the opaque session token string.
        """
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=ttl_hours)

        self._db.table("sessions").insert({
            "user_id":       user_id,
            "session_token": token,
            "created_at":    now.isoformat(),
            "expires_at":    expires.isoformat(),
        }).execute()

        return token

    def validate_session(self, session_token: str) -> str | None:
        """
        Validate a session token and return the user_id if valid, else None.
        Expired sessions are ignored (not deleted here for simplicity).
        """
        now = datetime.now(timezone.utc).isoformat()
        result = (
            self._db.table("sessions")
            .select("user_id, expires_at")
            .eq("session_token", session_token)
            .gt("expires_at", now)
            .execute()
        )
        if not result.data:
            return None
        return result.data[0]["user_id"]

    def delete_session(self, session_token: str) -> None:
        """Delete a session (logout)."""
        self._db.table("sessions").delete().eq("session_token", session_token).execute()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _user_from_row(row: dict) -> User:
        return User(
            id=row["id"],
            character_id=row["character_id"],
            character_name=row["character_name"],
            tier=row["tier"],
            tier_char_limit=row["tier_char_limit"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _character_from_row(row: dict) -> Character:
        return Character(
            id=row["id"],
            user_id=row["user_id"],
            character_id=row["character_id"],
            character_name=row["character_name"],
            is_primary=row["is_primary"],
            access_token=row.get("access_token"),
            refresh_token=row.get("refresh_token"),
            token_expiry=row.get("token_expiry"),
            accounting_level=row.get("accounting_level", 0),
            broker_level=row.get("broker_level", 0),
            last_synced=row.get("last_synced"),
            added_at=row["added_at"],
        )

    @staticmethod
    def _subscription_from_row(row: dict) -> Subscription:
        return Subscription(
            id=row["id"],
            user_id=row["user_id"],
            tier=row["tier"],
            starts_at=row["starts_at"],
            expires_at=row["expires_at"],
            is_active=row["is_active"],
            renewed_count=row.get("renewed_count", 0),
        )
