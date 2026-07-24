"""
src/core/payment_verifier.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Verifies premium subscription payments by polling the Moonpack Associates
corporation wallet journal via the dedicated corp API character.

Flow:
  1. Fetch recent journal entries from the corp wallet (up to 100 entries / 2 pages)
  2. Filter for player_donation entries where:
       - first_party_id matches the user's active character_id
       - amount matches 500_000_000 (Premium) or 1_000_000_000 (Corporate)
  3. Deduplicate against payments.esi_journal_id in Supabase
  4. If a match is found, call UserService.grant_subscription()

Designed to be called on-demand (user clicks "Check My Payment" in the UI).
On a future VPS deployment this can be promoted to a background polling loop
without any changes to this module.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from src.config import (
    CORP_PAYMENT_AMOUNT_CORPORATE,
    CORP_PAYMENT_AMOUNT_PREMIUM,
    MOONPACK_CORP_ID,
)
from src.core.esi_client import CorpWalletClient
from src.core.user_service import UserService


# ---------------------------------------------------------------------------
# Result enum
# ---------------------------------------------------------------------------

class VerificationResult(Enum):
    GRANTED        = "granted"        # Payment found and subscription activated
    ALREADY_ACTIVE = "already_active" # User already has an active subscription
    NOT_FOUND      = "not_found"      # No matching payment in recent journal
    DUPLICATE      = "duplicate"      # Journal entry already processed (dedup)
    ERROR          = "error"          # Unexpected failure during verification


# ---------------------------------------------------------------------------
# PaymentVerifier
# ---------------------------------------------------------------------------

class PaymentVerifier:
    """
    Verifies ISK payments to Moonpack Associates and grants subscription access.

    Args:
        corp_wallet: CorpWalletClient initialised with the corp API character's tokens.
        user_service: UserService instance for subscription grants and payment dedup.
        corp_id: Moonpack Associates corporation ID (default from config).
    """

    # Journal entry type CCP uses for direct ISK transfers between players/corps
    _DONATION_REF_TYPE = "player_donation"

    # Amount → tier mapping
    _AMOUNT_TO_TIER: dict[int, str] = {
        CORP_PAYMENT_AMOUNT_PREMIUM:   "premium",
        CORP_PAYMENT_AMOUNT_CORPORATE: "corporate",
    }

    def __init__(
        self,
        corp_wallet: CorpWalletClient,
        user_service: UserService,
        corp_id: int = MOONPACK_CORP_ID,
    ) -> None:
        self._wallet = corp_wallet
        self._svc = user_service
        self._corp_id = corp_id

    def check(self, user_id: str, character_id: int) -> VerificationResult:
        """
        Check whether the given character has made a qualifying payment to the corp.

        Args:
            user_id:      Supabase user UUID (the account to upgrade).
            character_id: EVE character ID whose wallet transfer to look for.
                          This is the character the user deposited FROM — it must
                          be one of their linked characters.

        Returns:
            VerificationResult enum value.
        """
        try:
            # Fast-path: already has an active subscription
            existing = self._svc.get_active_subscription(user_id)
            if existing is not None:
                return VerificationResult.ALREADY_ACTIVE

            # Fetch recent journal entries (up to 2 pages = ~100 entries)
            try:
                entries = self._wallet.get_journal(
                    corp_id=self._corp_id,
                    division=1,
                    pages=2,
                )
            except PermissionError:
                return VerificationResult.ERROR

            # Find qualifying entries for this character
            match = self._find_match(entries, character_id)
            if match is None:
                return VerificationResult.NOT_FOUND

            journal_id = match["id"]
            amount     = int(match["amount"])
            tier       = self._AMOUNT_TO_TIER[amount]

            # Deduplication check — has this journal entry already been processed?
            if self._is_duplicate(journal_id):
                return VerificationResult.DUPLICATE

            # Grant the subscription
            self._svc.grant_subscription(
                user_id=user_id,
                tier=tier,
                payment={
                    "character_id":   character_id,
                    "character_name": match.get("first_party_name", str(character_id)),
                    "amount_isk":     amount,
                    "esi_journal_id": journal_id,
                },
            )
            return VerificationResult.GRANTED

        except Exception:
            return VerificationResult.ERROR

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_match(
        self,
        entries: list[dict[str, Any]],
        character_id: int,
    ) -> dict[str, Any] | None:
        """
        Return the first journal entry that matches the character and amount.
        Returns None if no match is found.
        """
        qualifying_amounts = set(self._AMOUNT_TO_TIER.keys())

        for entry in entries:
            if entry.get("ref_type") != self._DONATION_REF_TYPE:
                continue
            if entry.get("first_party_id") != character_id:
                continue
            amount = int(entry.get("amount", 0))
            if amount not in qualifying_amounts:
                continue
            return entry

        return None

    def _is_duplicate(self, journal_id: int) -> bool:
        """Return True if this journal entry ID already exists in the payments table."""
        try:
            result = (
                self._svc._db.table("payments")
                .select("id")
                .eq("esi_journal_id", journal_id)
                .execute()
            )
            return bool(result.data)
        except Exception:
            # If we can't check, treat as not a duplicate to avoid blocking the user
            return False
