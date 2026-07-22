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
ESI_CALLBACK_URL: str = os.environ.get("ESI_CALLBACK_URL", "http://localhost:8000/callback")
ESI_SCOPES: list[str] = os.environ.get(
    "ESI_SCOPES",
    "esi-wallet.read_character_wallet.v1 esi-skills.read_skills.v1 esi-markets.read_character_orders.v1",
).split()

# ---------------------------------------------------------------------------
# Character
# ---------------------------------------------------------------------------
CHARACTER_ID: int = int(os.environ.get("CHARACTER_ID", "0"))

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
