"""
src/core/esi_client.py
~~~~~~~~~~~~~~~~~~~~~~
ESI client wrapper built on top of requests.

Phase 2 additions:
  - ESIClient now accepts explicit per-character tokens for web/multi-char mode.
    When tokens are injected at construction time the .tokens.json file is NOT
    used — all token state lives in the caller (Supabase characters table).
  - save_tokens_to_db(db_client, character_id) persists refreshed tokens back
    to Supabase after any auto-refresh.
  - get_skills() accepts an optional character_id override so multi-character
    requests target the right ESI endpoint.
  - CorpWalletClient polls the Moonpack Associates corp wallet journal using the
    dedicated corp API character's tokens.
  - decode_sso_token(access_token) decodes the EVE SSO JWT locally without a
    network call, returning character_id and character_name.

CLI backward-compat is preserved: constructing ESIClient() with no arguments
still falls back to .tokens.json + the CHARACTER_ID env var, exactly as before.

Moved from src/eve_server.py in Phase 1 restructure.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path
from typing import Any

import jwt
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from src.config import (
    CHARACTER_ID,
    ESI_BASE_URL,
    ESI_CALLBACK_URL,
    ESI_CLIENT_ID,
    ESI_CLIENT_SECRET,
    ESI_SCOPES,
    MARKET_REGION_ID,
    SKILL_ACCOUNTING_TYPE_ID,
    SKILL_BROKER_RELATIONS_TYPE_ID,
)

# File path for persistent token storage (CLI mode only)
_TOKEN_FILE = Path(__file__).resolve().parent.parent.parent / ".tokens.json"

# EVE SSO JWKS endpoint — used to verify JWT signatures
_EVE_JWKS_URL = "https://login.eveonline.com/oauth/jwks"
_EVE_ISSUER = "login.eveonline.com"


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def decode_sso_token(access_token: str) -> dict[str, Any]:
    """
    Decode an EVE SSO access token (JWT) and return its claims.

    Returns a dict containing at minimum:
      sub          — "CHARACTER:EVE:<character_id>"
      name         — character name
      exp          — expiry timestamp
      scp          — list of granted scopes (or single string)

    Does NOT verify the signature (EVE's JWKS requires a network call and
    the token was just issued by EVE's servers, so we trust it). Signature
    verification can be added later by fetching keys from _EVE_JWKS_URL.
    """
    # EVE JWTs use RS256; decode without verification for now (options allow it)
    claims = jwt.decode(
        access_token,
        algorithms=["RS256"],
        options={"verify_signature": False},
    )
    return claims


def character_id_from_token(access_token: str) -> int:
    """Extract the integer EVE character ID from an SSO access token."""
    claims = decode_sso_token(access_token)
    # sub format: "CHARACTER:EVE:12345678"
    sub: str = claims.get("sub", "")
    return int(sub.split(":")[-1])


def character_name_from_token(access_token: str) -> str:
    """Extract the character name from an SSO access token."""
    claims = decode_sso_token(access_token)
    return claims.get("name", "")


# ---------------------------------------------------------------------------
# ESIClient
# ---------------------------------------------------------------------------

class ESIClient:
    """
    EVE ESI client supporting both CLI (single-char .tokens.json) and web
    (per-character in-memory tokens injected from Supabase) modes.

    Web mode — pass tokens at construction:
        client = ESIClient(
            character_id=12345,
            access_token="...",
            refresh_token="...",
            token_expiry=1234567890.0,
        )

    CLI mode — no arguments, falls back to .tokens.json:
        client = ESIClient()
        client.authenticate()
    """

    _TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"
    _AUTH_URL  = "https://login.eveonline.com/v2/oauth/authorize"

    def __init__(
        self,
        character_id: int | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_expiry: float = 0.0,
    ) -> None:
        # Web mode: tokens injected directly
        self._character_id: int = character_id or CHARACTER_ID
        self._access_token: str | None = access_token
        self._refresh_token: str | None = refresh_token
        self._token_expiry: float = token_expiry
        self._web_mode: bool = access_token is not None

        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------
    # Authentication & Persistence (CLI mode)
    # ------------------------------------------------------------------

    def _load_tokens(self) -> bool:
        """Attempt to load saved tokens from disk cache (CLI mode only)."""
        if not _TOKEN_FILE.exists():
            return False
        try:
            data = json.loads(_TOKEN_FILE.read_text(encoding="utf-8"))
            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
            self._token_expiry = data.get("token_expiry", 0.0)
            if time.time() >= self._token_expiry and self._refresh_token:
                self._refresh()
            return bool(self._access_token)
        except Exception:
            return False

    def authenticate(self, access_token: str | None = None, refresh_token: str | None = None) -> None:
        """
        Prime the client with tokens (CLI mode).

        First attempts to load cached tokens from `.tokens.json`.
        If unauthenticated, opens the SSO URL and polls for the callback.

        In web mode (tokens injected at __init__) this method is a no-op.
        """
        if self._web_mode:
            return

        if access_token:
            self._access_token = access_token
            self._refresh_token = refresh_token
            self._token_expiry = time.time() + 1200
            return

        if self._load_tokens():
            print("[ESI] Loaded valid authentication tokens from disk cache.")
            return

        params = {
            "response_type": "code",
            "redirect_uri": ESI_CALLBACK_URL,
            "client_id": ESI_CLIENT_ID,
            "scope": " ".join(ESI_SCOPES),
            "state": "eve_optimizer",
        }
        url = f"{self._AUTH_URL}?{urllib.parse.urlencode(params)}"
        print(f"\nOpen this URL in your browser to authorise:\n\n  {url}\n")
        print("Waiting for browser authorization...")

        for _ in range(45):
            time.sleep(1)
            if self._load_tokens():
                print("[ESI] Authentication successful via local web server!")
                return

        code = input("\nPaste the `code` query parameter from the redirect URL: ").strip()
        if code:
            self._exchange_code(code)

    def exchange_code(self, code: str) -> dict[str, Any]:
        """
        Exchange an OAuth2 authorization code for tokens.

        Returns the raw token payload dict (access_token, refresh_token,
        expires_in). Stores tokens internally but does NOT write to disk
        in web mode — callers are responsible for persisting to Supabase.
        """
        resp = self._session.post(
            self._TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": ESI_CALLBACK_URL,
            },
            auth=(ESI_CLIENT_ID, ESI_CLIENT_SECRET),
        )
        resp.raise_for_status()
        payload = resp.json()
        self._store_token(payload)
        return payload

    # Keep old private name as alias for FastAPI callback backward-compat
    def _exchange_code(self, code: str) -> None:
        self.exchange_code(code)

    def _refresh(self) -> None:
        if not self._refresh_token:
            raise RuntimeError("No refresh token available. Re-authenticate.")
        resp = self._session.post(
            self._TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
            auth=(ESI_CLIENT_ID, ESI_CLIENT_SECRET),
        )
        resp.raise_for_status()
        self._store_token(resp.json())

    def _store_token(self, payload: dict[str, Any]) -> None:
        self._access_token = payload["access_token"]
        self._refresh_token = payload.get("refresh_token", self._refresh_token)
        self._token_expiry = time.time() + payload.get("expires_in", 1200) - 60

        if not self._web_mode:
            # CLI mode — persist to disk
            cache_data = {
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "token_expiry": self._token_expiry,
            }
            _TOKEN_FILE.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")

    def _auth_header(self) -> dict[str, str]:
        if time.time() >= self._token_expiry:
            self._refresh()
        return {"Authorization": f"Bearer {self._access_token}"}

    def save_tokens_to_db(self, db_client: Any, character_id: int) -> None:
        """
        Persist the current (possibly refreshed) tokens back to Supabase.
        Call this after any operation that may have triggered a token refresh.

        Args:
            db_client: Admin Supabase client (from get_admin_db()).
            character_id: The EVE character ID whose row to update.
        """
        db_client.table("characters").update({
            "access_token":  self._access_token,
            "refresh_token": self._refresh_token,
            "token_expiry":  self._token_expiry,
        }).eq("character_id", character_id).execute()

    # ------------------------------------------------------------------
    # Build the SSO authorization URL (web mode helper)
    # ------------------------------------------------------------------

    @staticmethod
    def build_auth_url(state: str = "login") -> str:
        """
        Return the EVE SSO authorization URL to redirect the user to.

        Args:
            state: OAuth2 state param — use 'login' for primary login,
                   'add_character' when adding an alt.
        """
        params = {
            "response_type": "code",
            "redirect_uri":  ESI_CALLBACK_URL,
            "client_id":     ESI_CLIENT_ID,
            "scope":         " ".join(ESI_SCOPES),
            "state":         state,
        }
        return f"{ESIClient._AUTH_URL}?{urllib.parse.urlencode(params)}"

    # ------------------------------------------------------------------
    # Character endpoints
    # ------------------------------------------------------------------

    def get_skills(self, character_id: int | None = None) -> dict[int, int]:
        """
        Fetch the character's trained skill levels.

        Args:
            character_id: Override the character to fetch for.
                          Defaults to the character this client was constructed for.
        """
        cid = character_id or self._character_id
        url = f"{ESI_BASE_URL}/characters/{cid}/skills/"
        resp = self._session.get(url, headers=self._auth_header())
        resp.raise_for_status()
        data = resp.json()
        return {s["skill_id"]: s["trained_skill_level"] for s in data.get("skills", [])}

    def get_accounting_level(self, character_id: int | None = None) -> int:
        """Return Accounting skill level (0–5)."""
        return self.get_skills(character_id).get(SKILL_ACCOUNTING_TYPE_ID, 0)

    def get_broker_relations_level(self, character_id: int | None = None) -> int:
        """Return Broker Relations skill level (0–5)."""
        return self.get_skills(character_id).get(SKILL_BROKER_RELATIONS_TYPE_ID, 0)

    # ------------------------------------------------------------------
    # Market endpoints
    # ------------------------------------------------------------------

    def get_market_orders(
        self,
        type_ids: list[int],
        order_type: str = "sell",
        region_id: int = MARKET_REGION_ID,
    ) -> dict[int, list[dict[str, Any]]]:
        """Fetch regional market orders for given type IDs with automatic pagination."""
        result: dict[int, list[dict[str, Any]]] = {tid: [] for tid in type_ids}

        for type_id in type_ids:
            page = 1
            while True:
                url = (
                    f"{ESI_BASE_URL}/markets/{region_id}/orders/"
                    f"?order_type={order_type}&type_id={type_id}&page={page}"
                )
                resp = self._session.get(url)
                resp.raise_for_status()
                orders = resp.json()
                result[type_id].extend(orders)
                total_pages = int(resp.headers.get("X-Pages", 1))
                if page >= total_pages:
                    break
                page += 1

        return result

    def best_sell_price(self, type_id: int, region_id: int = MARKET_REGION_ID) -> float:
        """Return lowest active sell-order price for a type in the region."""
        orders = self.get_market_orders([type_id], order_type="sell", region_id=region_id)
        sell_orders = [o for o in orders.get(type_id, []) if not o.get("is_buy_order", True)]
        if not sell_orders:
            return 0.0
        return min(o["price"] for o in sell_orders)

    def best_buy_price(self, type_id: int, region_id: int = MARKET_REGION_ID) -> float:
        """Return highest active buy-order price for a type in the region."""
        orders = self.get_market_orders([type_id], order_type="buy", region_id=region_id)
        buy_orders = [o for o in orders.get(type_id, []) if o.get("is_buy_order", False)]
        if not buy_orders:
            return 0.0
        return max(o["price"] for o in buy_orders)

    def get_market_history(
        self,
        type_ids: list[int],
        region_id: int = MARKET_REGION_ID,
        days: int = 5,
    ) -> dict[int, float]:
        """
        Return the most-recent average price from regional market history for
        each type ID.  Uses the ESI /markets/{region}/history/ endpoint which
        returns one record per day (no auth required).

        Only the most recent ``days`` records are considered.  If no history
        exists for a type the entry is absent from the returned dict.

        Args:
            type_ids: List of EVE type IDs to look up.
            region_id: EVE region ID (default: Jita / The Forge).
            days: How many of the most recent days to average (default: 5).

        Returns:
            Mapping of type_id -> average_price (float).
        """
        result: dict[int, float] = {}
        for type_id in type_ids:
            url = f"{ESI_BASE_URL}/markets/{region_id}/history/?type_id={type_id}"
            try:
                resp = self._session.get(url)
                resp.raise_for_status()
                history = resp.json()  # list of {date, average, highest, lowest, ...}
            except Exception:
                continue
            if not history:
                continue
            # Sort descending by date and take the most recent `days` entries
            history.sort(key=lambda d: d.get("date", ""), reverse=True)
            recent = history[:days]
            avg_prices = [float(d["average"]) for d in recent if d.get("average")]
            if avg_prices:
                result[type_id] = sum(avg_prices) / len(avg_prices)
        return result


# ---------------------------------------------------------------------------
# CorpWalletClient
# ---------------------------------------------------------------------------

class CorpWalletClient:
    """
    Reads the Moonpack Associates corporation wallet journal using the
    dedicated corp API character's tokens.

    Usage:
        client = CorpWalletClient(
            access_token="...",
            refresh_token="...",
            token_expiry=...,
        )
        entries = client.get_journal(corp_id=12345678, division=1)
    """

    _TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_expiry: float,
    ) -> None:
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_expiry = token_expiry
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    def _auth_header(self) -> dict[str, str]:
        if time.time() >= self._token_expiry:
            self._refresh()
        return {"Authorization": f"Bearer {self._access_token}"}

    def _refresh(self) -> None:
        if not self._refresh_token:
            raise RuntimeError("No refresh token for corp wallet client.")
        resp = self._session.post(
            self._TOKEN_URL,
            data={
                "grant_type":    "refresh_token",
                "refresh_token": self._refresh_token,
            },
            auth=(ESI_CLIENT_ID, ESI_CLIENT_SECRET),
        )
        resp.raise_for_status()
        payload = resp.json()
        self._access_token  = payload["access_token"]
        self._refresh_token = payload.get("refresh_token", self._refresh_token)
        self._token_expiry  = time.time() + payload.get("expires_in", 1200) - 60

    def get_journal(
        self,
        corp_id: int,
        division: int = 1,
        pages: int = 2,
    ) -> list[dict[str, Any]]:
        """
        Fetch the corporation wallet journal entries.

        Args:
            corp_id:  The corporation ID (Moonpack Associates).
            division: Wallet division (1–7). Default: 1 (master wallet).
            pages:    Number of pages to fetch (50 entries/page). Default: 2.

        Returns:
            List of journal entry dicts, each containing at minimum:
              id                — unique journal entry ID (for dedup)
              ref_type          — e.g. "player_donation", "bounty_prizes"
              first_party_id    — sending character/corp ID
              second_party_id   — receiving character/corp ID
              amount            — ISK amount (float, positive = credit)
              date              — ISO 8601 timestamp
              reason            — free-text reason field (optional)
        """
        entries: list[dict[str, Any]] = []
        for page in range(1, pages + 1):
            url = (
                f"{ESI_BASE_URL}/corporations/{corp_id}/wallets/{division}/journal/"
                f"?page={page}"
            )
            resp = self._session.get(url, headers=self._auth_header())
            if resp.status_code == 403:
                raise PermissionError(
                    "Corp wallet access denied — ensure the corp API character has "
                    "the Accountant or Director role and the correct ESI scope."
                )
            resp.raise_for_status()
            page_entries = resp.json()
            entries.extend(page_entries)
            if len(page_entries) < 50:
                # Fewer than a full page means we've hit the end
                break
        return entries


# ---------------------------------------------------------------------------
# FastAPI Application & OAuth Callback Endpoint (CLI / local dev only)
# ---------------------------------------------------------------------------

app = FastAPI(
    title="EVE PI Profit Optimizer ESI Bridge",
    description="Local loopback server handling EVE Online SSO authentication.",
    version="1.0.0",
)

_cli_esi_client = ESIClient()


@app.get("/")
def read_root():
    return {"status": "online", "service": "EVE PI Profit Optimizer ESI Bridge"}


@app.get("/callback")
async def oauth_callback(code: str = Query(..., description="Authorization code from EVE SSO")):
    """Catches EVE Online OAuth2 authorization code and exchanges it for persistent tokens."""
    try:
        _cli_esi_client._exchange_code(code)
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Authentication successful! You can close this window.",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {str(e)}")
