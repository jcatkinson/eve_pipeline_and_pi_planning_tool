"""
src/core/database.py
~~~~~~~~~~~~~~~~~~~~
PI blueprint database bootstrap — reads hardcoded PI chain data and writes
a local SQLite database with three tables:

    pi_items      — All PI items (type_id, name, tier, volume_m3)
    pi_blueprints — Each P1–P4 product and the quantity it yields per cycle
    pi_materials  — Input materials for each blueprint (type_id, quantity)

PI chain data is hardcoded from the SDE because:
  1. The SDE blueprint YAML is 200+ MB; parsing the full file for 50 PI items
     is wasteful on repeated runs.
  2. PI recipes are stable and very rarely patched.

To refresh this data after a CCP patch, update PI_CHAINS below and re-run:
    python -m src.core.database

Moved from src/databaseCreator.py in Phase 1 restructure.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from src.config import DB_PATH

# ---------------------------------------------------------------------------
# PI chain definitions
# Structure:
#   {
#     "output_type_id": int,
#     "output_name": str,
#     "output_tier": int,          # 1-4 (P1 = basic, P4 = advanced commodity)
#     "output_qty": int,           # units produced per cycle
#     "volume_m3": float,          # per unit
#     "planet_types": list[str],   # planet types that can produce this
#     "inputs": [
#         {"type_id": int, "name": str, "qty": int, "tier": int, "volume_m3": float}
#     ]
#   }
# ---------------------------------------------------------------------------

PI_CHAINS: list[dict[str, Any]] = [
    # ------------------------------------------------------------------
    # P1 — Basic Industry Facility outputs (extracted from P0 raw resources)
    # ------------------------------------------------------------------
    {
        "output_type_id": 2267, "output_name": "Reactive Metals",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["barren", "plasma"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2268, "output_name": "Precious Metals",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["plasma", "barren"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2306, "output_name": "Toxic Metals",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["barren", "lava"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2307, "output_name": "Chiral Structures",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["lava", "barren"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2309, "output_name": "Biofuels",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["temperate", "gas"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2310, "output_name": "Proteins",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["temperate", "oceanic"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2311, "output_name": "Biomass",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["oceanic", "temperate"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2312, "output_name": "Bacteria",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["temperate", "oceanic", "gas"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2313, "output_name": "Oxidizing Compound",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["gas", "storm"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2315, "output_name": "Ionic Solutions",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["gas", "storm"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2316, "output_name": "Noble Metals",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["barren", "plasma"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2317, "output_name": "Silicates",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["lava", "barren"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2318, "output_name": "Electrolytes",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["storm", "gas"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2319, "output_name": "Oxygen",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["gas", "ice"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2321, "output_name": "Plasmoids",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["plasma", "storm"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 2322, "output_name": "Suspended Plasma",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["plasma", "storm", "lava"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    {
        "output_type_id": 9828, "output_name": "Water",
        "output_tier": 1, "output_qty": 3000, "volume_m3": 0.01,
        "planet_types": ["ice", "gas", "oceanic", "temperate"],
        "inputs": [{"type_id": 18, "name": "Tritanium", "qty": 3000, "tier": 0, "volume_m3": 0.01}],
    },
    # ------------------------------------------------------------------
    # P2 — Advanced Industry Facility outputs (2× P1 inputs)
    # ------------------------------------------------------------------
    {
        "output_type_id": 44, "output_name": "Enriched Uranium",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["lava", "barren"],
        "inputs": [
            {"type_id": 2306, "name": "Toxic Metals",    "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 2317, "name": "Silicates",        "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 2329, "output_name": "Mechanical Parts",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["barren", "plasma"],
        "inputs": [
            {"type_id": 2267, "name": "Reactive Metals",  "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 2316, "name": "Noble Metals",     "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 2327, "output_name": "Consumer Electronics",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["lava", "barren", "plasma"],
        "inputs": [
            {"type_id": 2307, "name": "Chiral Structures","qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 2317, "name": "Silicates",         "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 2332, "output_name": "Construction Blocks",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["barren", "lava"],
        "inputs": [
            {"type_id": 2267, "name": "Reactive Metals",  "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 2306, "name": "Toxic Metals",      "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 9830, "output_name": "Coolant",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["gas", "ice"],
        "inputs": [
            {"type_id": 2313, "name": "Oxidizing Compound","qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 9828, "name": "Water",              "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 9832, "output_name": "Rocket Fuel",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["ice", "gas"],
        "inputs": [
            {"type_id": 2319, "name": "Oxygen",             "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 2315, "name": "Ionic Solutions",    "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 2463, "output_name": "Transmitter",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["plasma", "storm"],
        "inputs": [
            {"type_id": 2321, "name": "Plasmoids",          "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 2318, "name": "Electrolytes",       "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 2344, "output_name": "Livestock",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["temperate"],
        "inputs": [
            {"type_id": 2309, "name": "Biofuels",           "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 2310, "name": "Proteins",           "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 2346, "output_name": "Biocells",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["temperate", "oceanic"],
        "inputs": [
            {"type_id": 2309, "name": "Biofuels",           "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 2311, "name": "Biomass",             "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 2348, "output_name": "Microfiber Shielding",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["gas", "temperate"],
        "inputs": [
            {"type_id": 2319, "name": "Oxygen",             "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 2312, "name": "Bacteria",           "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 9836, "output_name": "Superconductors",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["storm", "plasma"],
        "inputs": [
            {"type_id": 2321, "name": "Plasmoids",           "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 9828, "name": "Water",               "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 9838, "output_name": "Synthetic Oil",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["barren", "ice"],
        "inputs": [
            {"type_id": 2267, "name": "Reactive Metals",    "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 9828, "name": "Water",              "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 9840, "output_name": "Test Cultures",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["oceanic", "gas"],
        "inputs": [
            {"type_id": 2312, "name": "Bacteria",           "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 9828, "name": "Water",              "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 9842, "output_name": "Supertensile Plastics",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["gas", "temperate"],
        "inputs": [
            {"type_id": 2313, "name": "Oxidizing Compound", "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 2310, "name": "Proteins",           "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 2353, "output_name": "Polyaramids",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["gas", "temperate"],
        "inputs": [
            {"type_id": 2319, "name": "Oxygen",             "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 2310, "name": "Proteins",           "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    {
        "output_type_id": 2354, "output_name": "Miniature Electronics",
        "output_tier": 2, "output_qty": 100, "volume_m3": 0.38,
        "planet_types": ["lava", "barren"],
        "inputs": [
            {"type_id": 2307, "name": "Chiral Structures",  "qty": 40, "tier": 1, "volume_m3": 0.01},
            {"type_id": 2268, "name": "Precious Metals",    "qty": 40, "tier": 1, "volume_m3": 0.01},
        ],
    },
    # ------------------------------------------------------------------
    # P3 — High-Tech Production Plant outputs (3× P2 inputs)
    # ------------------------------------------------------------------
    {
        "output_type_id": 2867, "output_name": "Robotics",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["barren", "lava", "plasma"],
        "inputs": [
            {"type_id": 9836, "name": "Superconductors",    "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2329, "name": "Mechanical Parts",   "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2327, "name": "Consumer Electronics","qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2868, "output_name": "Hazmat Detection Systems",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["barren", "lava"],
        "inputs": [
            {"type_id": 44,   "name": "Enriched Uranium",   "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9832, "name": "Rocket Fuel",         "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2354, "name": "Miniature Electronics","qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2869, "output_name": "Mechanical Parts",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["barren"],
        "inputs": [
            {"type_id": 2329, "name": "Mechanical Parts",   "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2332, "name": "Construction Blocks","qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9838, "name": "Synthetic Oil",       "qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2870, "output_name": "Biotech Research Reports",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["temperate", "oceanic"],
        "inputs": [
            {"type_id": 2346, "name": "Biocells",           "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9840, "name": "Test Cultures",       "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9842, "name": "Supertensile Plastics","qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2871, "output_name": "Guidance Systems",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["storm", "plasma"],
        "inputs": [
            {"type_id": 2463, "name": "Transmitter",        "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9836, "name": "Superconductors",    "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9830, "name": "Coolant",             "qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2872, "output_name": "Ukomi Super Conductors",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["storm", "gas"],
        "inputs": [
            {"type_id": 9836, "name": "Superconductors",    "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9832, "name": "Rocket Fuel",         "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2348, "name": "Microfiber Shielding","qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2875, "output_name": "Broadcast Node",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["lava", "temperate"],
        "inputs": [
            {"type_id": 2327, "name": "Consumer Electronics","qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2463, "name": "Transmitter",         "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9836, "name": "Superconductors",     "qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2876, "output_name": "Integrity Response Drones",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["oceanic", "gas"],
        "inputs": [
            {"type_id": 9836, "name": "Superconductors",    "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2346, "name": "Biocells",           "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9830, "name": "Coolant",             "qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2877, "output_name": "Nano-Factory",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["barren", "plasma"],
        "inputs": [
            {"type_id": 2329, "name": "Mechanical Parts",   "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2463, "name": "Transmitter",        "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9836, "name": "Superconductors",    "qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2878, "output_name": "Organic Mortar Applicators",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["temperate"],
        "inputs": [
            {"type_id": 2344, "name": "Livestock",          "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9842, "name": "Supertensile Plastics","qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2346, "name": "Biocells",           "qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2879, "output_name": "Recursive Computing Module",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["gas", "storm"],
        "inputs": [
            {"type_id": 2327, "name": "Consumer Electronics","qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9836, "name": "Superconductors",    "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2354, "name": "Miniature Electronics","qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2880, "output_name": "Self-Harmonizing Power Core",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["plasma", "lava"],
        "inputs": [
            {"type_id": 2321, "name": "Plasmoids",          "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9836, "name": "Superconductors",    "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2463, "name": "Transmitter",        "qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2881, "output_name": "Sterile Conduits",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["oceanic", "gas"],
        "inputs": [
            {"type_id": 9830, "name": "Coolant",             "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2346, "name": "Biocells",           "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9840, "name": "Test Cultures",      "qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    {
        "output_type_id": 2882, "output_name": "Wetware Mainframe",
        "output_tier": 3, "output_qty": 10, "volume_m3": 1.5,
        "planet_types": ["oceanic", "temperate"],
        "inputs": [
            {"type_id": 2346, "name": "Biocells",           "qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 2327, "name": "Consumer Electronics","qty": 6, "tier": 2, "volume_m3": 0.38},
            {"type_id": 9840, "name": "Test Cultures",      "qty": 6, "tier": 2, "volume_m3": 0.38},
        ],
    },
    # ------------------------------------------------------------------
    # P4 — Specialized Industry Facility outputs (3× P3 inputs)
    # ------------------------------------------------------------------
    {
        "output_type_id": 2886, "output_name": "Broadcast Node",
        "output_tier": 4, "output_qty": 1, "volume_m3": 6.0,
        "planet_types": ["any"],
        "inputs": [
            {"type_id": 2875, "name": "Broadcast Node",          "qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2879, "name": "Recursive Computing Module","qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2882, "name": "Wetware Mainframe",        "qty": 6, "tier": 3, "volume_m3": 1.5},
        ],
    },
    {
        "output_type_id": 2887, "output_name": "Integrity Response Drones",
        "output_tier": 4, "output_qty": 1, "volume_m3": 6.0,
        "planet_types": ["any"],
        "inputs": [
            {"type_id": 2876, "name": "Integrity Response Drones","qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2867, "name": "Robotics",                 "qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2878, "name": "Organic Mortar Applicators","qty": 6, "tier": 3, "volume_m3": 1.5},
        ],
    },
    {
        "output_type_id": 2888, "output_name": "Nano-Factory",
        "output_tier": 4, "output_qty": 1, "volume_m3": 6.0,
        "planet_types": ["any"],
        "inputs": [
            {"type_id": 2877, "name": "Nano-Factory",             "qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2867, "name": "Robotics",                 "qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2871, "name": "Guidance Systems",         "qty": 6, "tier": 3, "volume_m3": 1.5},
        ],
    },
    {
        "output_type_id": 2889, "output_name": "Organic Mortar Applicators",
        "output_tier": 4, "output_qty": 1, "volume_m3": 6.0,
        "planet_types": ["any"],
        "inputs": [
            {"type_id": 2878, "name": "Organic Mortar Applicators","qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2870, "name": "Biotech Research Reports", "qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2881, "name": "Sterile Conduits",         "qty": 6, "tier": 3, "volume_m3": 1.5},
        ],
    },
    {
        "output_type_id": 2890, "output_name": "Recursive Computing Module",
        "output_tier": 4, "output_qty": 1, "volume_m3": 6.0,
        "planet_types": ["any"],
        "inputs": [
            {"type_id": 2879, "name": "Recursive Computing Module","qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2872, "name": "Ukomi Super Conductors",   "qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2867, "name": "Robotics",                 "qty": 6, "tier": 3, "volume_m3": 1.5},
        ],
    },
    {
        "output_type_id": 2891, "output_name": "Self-Harmonizing Power Core",
        "output_tier": 4, "output_qty": 1, "volume_m3": 6.0,
        "planet_types": ["any"],
        "inputs": [
            {"type_id": 2880, "name": "Self-Harmonizing Power Core","qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2868, "name": "Hazmat Detection Systems",  "qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2871, "name": "Guidance Systems",          "qty": 6, "tier": 3, "volume_m3": 1.5},
        ],
    },
    {
        "output_type_id": 2892, "output_name": "Sterile Conduits",
        "output_tier": 4, "output_qty": 1, "volume_m3": 6.0,
        "planet_types": ["any"],
        "inputs": [
            {"type_id": 2881, "name": "Sterile Conduits",          "qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2876, "name": "Integrity Response Drones", "qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2882, "name": "Wetware Mainframe",         "qty": 6, "tier": 3, "volume_m3": 1.5},
        ],
    },
    {
        "output_type_id": 2893, "output_name": "Wetware Mainframe",
        "output_tier": 4, "output_qty": 1, "volume_m3": 6.0,
        "planet_types": ["any"],
        "inputs": [
            {"type_id": 2882, "name": "Wetware Mainframe",         "qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2870, "name": "Biotech Research Reports",  "qty": 6, "tier": 3, "volume_m3": 1.5},
            {"type_id": 2875, "name": "Broadcast Node",            "qty": 6, "tier": 3, "volume_m3": 1.5},
        ],
    },
]


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------

def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pi_items (
            type_id     INTEGER PRIMARY KEY,
            name        TEXT    NOT NULL,
            tier        INTEGER NOT NULL,  -- 0=raw, 1=P1, 2=P2, 3=P3, 4=P4
            volume_m3   REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pi_blueprints (
            blueprint_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            output_type_id  INTEGER NOT NULL REFERENCES pi_items(type_id),
            output_qty      INTEGER NOT NULL,
            planet_types    TEXT    NOT NULL   -- JSON array e.g. '["barren","lava"]'
        );

        CREATE TABLE IF NOT EXISTS pi_materials (
            material_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            blueprint_id    INTEGER NOT NULL REFERENCES pi_blueprints(blueprint_id),
            input_type_id   INTEGER NOT NULL REFERENCES pi_items(type_id),
            input_qty       INTEGER NOT NULL
        );
    """)
    conn.commit()


def _seed_data(conn: sqlite3.Connection) -> None:
    import json

    # Collect all items (inputs + outputs) de-duped
    items: dict[int, tuple[str, int, float]] = {}
    for chain in PI_CHAINS:
        items[chain["output_type_id"]] = (chain["output_name"], chain["output_tier"], chain["volume_m3"])
        for inp in chain["inputs"]:
            if inp["type_id"] not in items:
                items[inp["type_id"]] = (inp["name"], inp["tier"], inp["volume_m3"])

    conn.executemany(
        "INSERT OR REPLACE INTO pi_items (type_id, name, tier, volume_m3) VALUES (?, ?, ?, ?)",
        [(tid, name, tier, vol) for tid, (name, tier, vol) in items.items()],
    )

    for chain in PI_CHAINS:
        cursor = conn.execute(
            "INSERT INTO pi_blueprints (output_type_id, output_qty, planet_types) VALUES (?, ?, ?)",
            (chain["output_type_id"], chain["output_qty"], json.dumps(chain["planet_types"])),
        )
        bp_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO pi_materials (blueprint_id, input_type_id, input_qty) VALUES (?, ?, ?)",
            [(bp_id, inp["type_id"], inp["qty"]) for inp in chain["inputs"]],
        )

    conn.commit()


def build_database(db_path: Path = DB_PATH) -> None:
    """Create (or overwrite) the PI blueprints SQLite database."""
    import sys
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        _create_tables(conn)
        _seed_data(conn)
        print(f"[databaseCreator] Database built at: {db_path}", file=sys.stderr)
        print(f"[databaseCreator] {len(PI_CHAINS)} PI chains seeded.", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    build_database()
