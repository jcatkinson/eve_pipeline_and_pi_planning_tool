"""
src/config.py
~~~~~~~~~~~~~
Loads environment variables and exposes typed application-wide constants.
All ESI, market, and risk parameters are centralised here.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env from the project root (eve_optimizer/ directory)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# ESI / OAuth2
# ---------------------------------------------------------------------------
ESI_BASE_URL: str = "https://esi.evetech.net/latest"
ESI_CLIENT_ID: str = os.environ.get("ESI_CLIENT_ID", "")
ESI_CLIENT_SECRET: str = os.environ.get("ESI_CLIENT_SECRET", "")
ESI_CALLBACK_URL: str = os.environ.get("ESI_CALLBACK_URL", "")
ESI_SCOPES: list[str] = os.environ.get(
    "ESI_SCOPES",
    "esi-wallet.read_character_wallet.v1 esi-skills.read_skills.v1 esi-markets.read_character_orders.v1 esi-wallet.read_corporation_wallets.v1",
).split()

# Corp wallet scope used by the dedicated corp API character
ESI_CORP_WALLET_SCOPE: str = "esi-wallet.read_corporation_wallets.v1"

# ---------------------------------------------------------------------------
# Character
# ---------------------------------------------------------------------------
CHARACTER_ID: int = int(os.environ.get("CHARACTER_ID", "0"))

# Owner's primary EVE character ID — grants permanent "admin" tier (in-memory only).
# Set to 0 to disable the admin override entirely.
ADMIN_CHARACTER_ID: int = int(os.environ.get("ADMIN_CHARACTER_ID", "0"))

# ---------------------------------------------------------------------------
# Market region — The Forge (Jita)
# ---------------------------------------------------------------------------
MARKET_REGION_ID: int = int(os.environ.get("MARKET_REGION_ID", "10000002"))

# ---------------------------------------------------------------------------
# ESI Skill type IDs used in fee calculations
# ---------------------------------------------------------------------------
SKILL_ACCOUNTING_TYPE_ID: int = 16622       # Accounting      — reduces sales tax
SKILL_BROKER_RELATIONS_TYPE_ID: int = 3446  # Broker Relations — reduces broker fee

# ---------------------------------------------------------------------------
# Base transaction costs (before skill adjustments)
# CCP defaults as of latest patch notes.
# ---------------------------------------------------------------------------
BASE_SALES_TAX_RATE: float = 0.08        # 8% base
BASE_BROKER_FEE_RATE: float = 0.03       # 3% base (NPC station Jita)

# Sales tax reduction per Accounting level: 11% per level
ACCOUNTING_TAX_REDUCTION_PER_LEVEL: float = 0.11

# Broker fee reduction per Broker Relations level: 3% per level
BROKER_RELATIONS_FEE_REDUCTION_PER_LEVEL: float = 0.03

# ---------------------------------------------------------------------------
# Transport risk
# Manual low-sec hauling risk expressed as a fraction of total cargo value.
# e.g. 0.05 == 5% expected loss per run factored into P&L.
# ---------------------------------------------------------------------------
TRANSPORT_RISK_FACTOR: float = float(os.environ.get("TRANSPORT_RISK_FACTOR", "0.05"))

# ---------------------------------------------------------------------------
# Planetary Industry — planet types with PI capability
# ---------------------------------------------------------------------------
PLANET_TYPES: list[str] = [
    "barren",
    "temperate",
    "lava",
    "oceanic",
    "gas",
    "storm",
    "plasma",
    "ice",
]

# ---------------------------------------------------------------------------
# SQLite database path
# ---------------------------------------------------------------------------
DB_PATH: Path = _PROJECT_ROOT / "pi_blueprints.db"

# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY: str = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# ---------------------------------------------------------------------------
# Corp verification (Moonpack Associates)
# ---------------------------------------------------------------------------
CORP_API_CHARACTER_ID: int = int(os.environ.get("CORP_API_CHARACTER_ID", "0"))
MOONPACK_CORP_ID: int = int(os.environ.get("MOONPACK_CORP_ID", "0"))

# ISK payment amounts per tier
CORP_PAYMENT_AMOUNT_PREMIUM: int = 500_000_000       # 500M ISK
CORP_PAYMENT_AMOUNT_CORPORATE: int = 1_000_000_000   # 1B ISK

# ---------------------------------------------------------------------------
# Subscription tier character limits
# ---------------------------------------------------------------------------
TIER_CHAR_LIMITS: dict[str, int | None] = {
    "free":      2,
    "premium":   10,
    "corporate": None,   # None = unlimited
}
