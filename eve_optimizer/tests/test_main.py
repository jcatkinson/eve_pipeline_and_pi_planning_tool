"""
tests/test_main.py
~~~~~~~~~~~~~~~~~~
Unit and integration tests for the EVE PI Profit Engine.
Run with:  pytest tests/ -v

All ESI calls are mocked — no network access required.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.utils.helpers import (
    effective_broker_fee,
    effective_sales_tax,
    format_isk,
    isk_per_m3,
    net_sell_value,
    total_volume,
)


# ===========================================================================
# helpers.py — pure math
# ===========================================================================

class TestFormatISK:
    def test_billions(self):
        assert format_isk(1_500_000_000) == "1.50B ISK"

    def test_millions(self):
        assert format_isk(4_250_000) == "4.25M ISK"

    def test_thousands(self):
        assert format_isk(12_500) == "12.50K ISK"

    def test_units(self):
        assert format_isk(999) == "999.00 ISK"

    def test_negative(self):
        assert format_isk(-2_000_000) == "-2.00M ISK"


class TestEffectiveSalesTax:
    """
    Base rate 8%.  Accounting L5 should reduce it by 11% * 5 = 55%:
    0.08 * (1 - 0.55) = 0.08 * 0.45 = 0.036
    """
    def test_level_0(self):
        assert effective_sales_tax(0) == pytest.approx(0.08)

    def test_level_5(self):
        assert effective_sales_tax(5) == pytest.approx(0.08 * 0.45)

    def test_level_3(self):
        assert effective_sales_tax(3) == pytest.approx(0.08 * (1 - 0.33))


class TestEffectiveBrokerFee:
    """
    Base rate 3%.  Broker Relations L5: 0.03 * (1 - 0.15) = 0.03 * 0.85 = 0.0255
    """
    def test_level_0(self):
        assert effective_broker_fee(0) == pytest.approx(0.03)

    def test_level_5(self):
        assert effective_broker_fee(5) == pytest.approx(0.03 * 0.85)


class TestNetSellValue:
    def test_basic_no_risk(self):
        # 100 units at 1000 ISK, 8% tax, 3% broker, no transport risk
        # gross = 100_000; deductions = 11% = 11_000; net = 89_000
        val = net_sell_value(1000.0, 100, 0.08, 0.03, 0.0)
        assert val == pytest.approx(89_000.0)

    def test_with_transport_risk(self):
        # Additional 5% risk → total deductions 16%
        val = net_sell_value(1000.0, 100, 0.08, 0.03, 0.05)
        assert val == pytest.approx(84_000.0)

    def test_zero_price(self):
        assert net_sell_value(0.0, 100, 0.08, 0.03, 0.05) == 0.0


class TestVolumeHelpers:
    def test_total_volume(self):
        assert total_volume(0.38, 100) == pytest.approx(38.0)

    def test_isk_per_m3(self):
        assert isk_per_m3(38_000.0, 38.0) == pytest.approx(1000.0)

    def test_isk_per_m3_zero_volume(self):
        assert isk_per_m3(1000.0, 0.0) == 0.0


# ===========================================================================
# databaseCreator.py
# ===========================================================================

class TestDatabaseCreator:
    def test_build_and_query(self, tmp_path):
        from src.databaseCreator import build_database

        db = tmp_path / "test_pi.db"
        build_database(db_path=db)

        conn = sqlite3.connect(db)
        count_items = conn.execute("SELECT COUNT(*) FROM pi_items").fetchone()[0]
        count_bps   = conn.execute("SELECT COUNT(*) FROM pi_blueprints").fetchone()[0]
        count_mats  = conn.execute("SELECT COUNT(*) FROM pi_materials").fetchone()[0]
        conn.close()

        assert count_items > 0,  "pi_items should be populated"
        assert count_bps > 0,    "pi_blueprints should be populated"
        assert count_mats > 0,   "pi_materials should be populated"

    def test_tiers_present(self, tmp_path):
        from src.databaseCreator import build_database

        db = tmp_path / "test_pi.db"
        build_database(db_path=db)

        conn = sqlite3.connect(db)
        tiers = {r[0] for r in conn.execute("SELECT DISTINCT tier FROM pi_items").fetchall()}
        conn.close()

        assert 1 in tiers, "P1 items should be in database"
        assert 2 in tiers, "P2 items should be in database"
        assert 3 in tiers, "P3 items should be in database"
        assert 4 in tiers, "P4 items should be in database"


# ===========================================================================
# profit_engine.py
# ===========================================================================

class TestProfitEngine:
    """Tests for the ProfitEngine using a real temp database and a mock ESI client."""

    @pytest.fixture
    def db_path(self, tmp_path) -> Path:
        from src.databaseCreator import build_database
        db = tmp_path / "engine_test.db"
        build_database(db_path=db)
        return db

    @pytest.fixture
    def mock_esi(self):
        """Mock ESI that returns static prices for all PI items."""
        from src.main import _MockESIClient
        return _MockESIClient()

    def test_run_returns_results(self, db_path, mock_esi):
        from src.profit_engine import ProfitEngine
        engine = ProfitEngine(esi_client=mock_esi, db_path=db_path)
        results = engine.run(min_tier=3)
        assert len(results) > 0

    def test_results_sorted_by_delta(self, db_path, mock_esi):
        from src.profit_engine import ProfitEngine
        engine = ProfitEngine(esi_client=mock_esi, db_path=db_path)
        results = engine.run(min_tier=3)
        deltas = [r.delta_isk for r in results]
        assert deltas == sorted(deltas, reverse=True)

    def test_recommendation_matches_delta(self, db_path, mock_esi):
        from src.profit_engine import ProfitEngine
        engine = ProfitEngine(esi_client=mock_esi, db_path=db_path)
        results = engine.run(min_tier=3)
        for r in results:
            if r.delta_isk > 0:
                assert r.recommendation == "PROCESS & MANUFACTURE"
            else:
                assert r.recommendation == "SELL RAW"

    def test_accounting_skill_reduces_tax(self, db_path, mock_esi):
        from src.profit_engine import ProfitEngine
        engine_l0 = ProfitEngine(esi_client=mock_esi, accounting_level=0, db_path=db_path)
        engine_l5 = ProfitEngine(esi_client=mock_esi, accounting_level=5, db_path=db_path)
        assert engine_l5.sales_tax_rate < engine_l0.sales_tax_rate

    def test_broker_relations_reduces_fee(self, db_path, mock_esi):
        from src.profit_engine import ProfitEngine
        engine_l0 = ProfitEngine(esi_client=mock_esi, broker_relations_level=0, db_path=db_path)
        engine_l5 = ProfitEngine(esi_client=mock_esi, broker_relations_level=5, db_path=db_path)
        assert engine_l5.broker_fee_rate < engine_l0.broker_fee_rate

    def test_planet_type_filter(self, db_path, mock_esi):
        from src.profit_engine import ProfitEngine
        engine = ProfitEngine(
            esi_client=mock_esi,
            planet_type_filter=["barren"],
            db_path=db_path,
        )
        results = engine.run(min_tier=3)
        # All results should involve barren-compatible chains or "any"
        for r in results:
            assert "barren" in r.planet_types or r.planet_types == ["any"]

    def test_p4_only(self, db_path, mock_esi):
        from src.profit_engine import ProfitEngine
        engine = ProfitEngine(esi_client=mock_esi, db_path=db_path)
        results = engine.run(min_tier=4)
        assert all(r.output_tier == 4 for r in results)

    def test_transport_risk_reduces_net(self, db_path, mock_esi):
        from src.profit_engine import ProfitEngine
        engine_no_risk   = ProfitEngine(esi_client=mock_esi, transport_risk_factor=0.0, db_path=db_path)
        engine_with_risk = ProfitEngine(esi_client=mock_esi, transport_risk_factor=0.10, db_path=db_path)
        r0 = engine_no_risk.run(min_tier=3)
        r1 = engine_with_risk.run(min_tier=3)
        # Both sets should have results; process net should be lower with risk
        assert r0[0].process_net_isk > r1[0].process_net_isk


# ===========================================================================
# main.py CLI integration
# ===========================================================================

class TestCLI:
    def test_no_auth_runs(self, tmp_path, capsys):
        """--no-auth should complete without errors using mock prices."""
        import sys
        from src.main import main

        # Point DB to a temp location so the test auto-builds it
        with patch("src.main.DB_PATH", tmp_path / "cli_test.db"), \
             patch("src.databaseCreator.DB_PATH", tmp_path / "cli_test.db"), \
             patch("src.profit_engine.DB_PATH", tmp_path / "cli_test.db"):
            exit_code = main(["--no-auth", "--tier", "3"])

        assert exit_code == 0

    def test_json_output(self, tmp_path, capsys):
        """--json flag should emit valid JSON to stdout."""
        from src.main import main

        with patch("src.main.DB_PATH", tmp_path / "json_test.db"), \
             patch("src.databaseCreator.DB_PATH", tmp_path / "json_test.db"), \
             patch("src.profit_engine.DB_PATH", tmp_path / "json_test.db"):
            exit_code = main(["--no-auth", "--json", "--tier", "3"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert exit_code == 0

    def test_top_flag(self, tmp_path, capsys):
        """--top 3 should return at most 3 results."""
        from src.main import main

        with patch("src.main.DB_PATH", tmp_path / "top_test.db"), \
             patch("src.databaseCreator.DB_PATH", tmp_path / "top_test.db"), \
             patch("src.profit_engine.DB_PATH", tmp_path / "top_test.db"):
            exit_code = main(["--no-auth", "--json", "--top", "3"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) <= 3
        assert exit_code == 0
