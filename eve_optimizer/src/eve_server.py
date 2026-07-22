"""
src/eve_server.py
~~~~~~~~~~~~~~~~~
ESI client wrapper built on top of requests.
Handles OAuth2 token acquisition/refresh with disk persistence
and exposes typed fetch methods for ESI endpoints.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path
from typing import Any

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

# File path for persistent token storage
_TOKEN_FILE = Path(__file__).resolve().parent.parent / ".tokens.json"


class ESIClient:
    """
    Minimal ESI client with OAuth2 authorization-code flow and disk persistence.
    """

    _TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"
    _AUTH_URL = "https://login.eveonline.com/v2/oauth/authorize"

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expiry: float = 0.0
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------
    # Authentication & Persistence
    # ------------------------------------------------------------------

    def _load_tokens(self) -> bool:
        """Attempt to load saved tokens from disk cache."""
        if not _TOKEN_FILE.exists():
            return False

        try:
            data = json.loads(_TOKEN_FILE.read_text(encoding="utf-8"))
            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
            self._token_expiry = data.get("token_expiry", 0.0)

            # If access token is expired but we have a refresh token, auto-refresh
            if time.time() >= self._token_expiry and self._refresh_token:
                self._refresh()

            return bool(self._access_token)
        except Exception:
            return False

    def authenticate(self, access_token: str | None = None, refresh_token: str | None = None) -> None:
        """
        Prime the client with tokens.

        First attempts to load cached tokens from `.tokens.json`.
        If unauthenticated, opens the SSO URL and polls for the callback.
        """
        if access_token:
            self._access_token = access_token
            self._refresh_token = refresh_token
            self._token_expiry = time.time() + 1200
            return

        # 1. Check if valid cached tokens exist on disk
        if self._load_tokens():
            print("[ESI] Loaded valid authentication tokens from disk cache.")
            return

        # 2. Print authorization URL for browser
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

        # 3. Poll for background server token capture (up to 45 seconds)
        for _ in range(45):
            time.sleep(1)
            if self._load_tokens():
                print("[ESI] Authentication successful via local web server!")
                return

        # 4. Fallback manual prompt if local server callback was not caught
        code = input("\nPaste the `code` query parameter from the redirect URL: ").strip()
        if code:
            self._exchange_code(code)

    def _exchange_code(self, code: str) -> None:
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
        self._store_token(resp.json())

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
        self._token_expiry = time.time() + payload.get("expires_in", 1200) - 60  # 60s safety buffer

        # Save to disk cache for future CLI executions
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

    # ------------------------------------------------------------------
    # Character endpoints
    # ------------------------------------------------------------------

    def get_skills(self) -> dict[int, int]:
        """Fetch the character's trained skill levels."""
        url = f"{ESI_BASE_URL}/characters/{CHARACTER_ID}/skills/"
        resp = self._session.get(url, headers=self._auth_header())
        resp.raise_for_status()
        data = resp.json()
        return {s["skill_id"]: s["trained_skill_level"] for s in data.get("skills", [])}

    def get_accounting_level(self) -> int:
        """Return Accounting skill level (0–5)."""
        skills = self.get_skills()
        return skills.get(SKILL_ACCOUNTING_TYPE_ID, 0)

    def get_broker_relations_level(self) -> int:
        """Return Broker Relations skill level (0–5)."""
        skills = self.get_skills()
        return skills.get(SKILL_BROKER_RELATIONS_TYPE_ID, 0)

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


# ---------------------------------------------------------------------------
# FastAPI Application & OAuth Callback Endpoint
# ---------------------------------------------------------------------------

app = FastAPI(
    title="EVE PI Profit Optimizer ESI Bridge",
    description="Local loopback server handling EVE Online SSO authentication.",
    version="1.0.0",
)

esi_client = ESIClient()


@app.get("/")
def read_root():
    return {"status": "online", "service": "EVE PI Profit Optimizer ESI Bridge"}


@app.get("/callback")
async def oauth_callback(code: str = Query(..., description="Authorization code from EVE SSO")):
    """Catches EVE Online OAuth2 authorization code and exchanges it for persistent tokens."""
    try:
        esi_client._exchange_code(code)
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Authentication successful! Tokens securely acquired and stored. You can close this window.",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {str(e)}")