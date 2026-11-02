#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest
import tempfile
import pandas as pd
from services.simulation_store import SimulationStore, defaults
from services.simulation_service import build_plan, symbols_for, allocation, portfolio
from strategies.bottom_fishing import run_bottom_fishing_strategy, get_bottom_fishing_trades
from strategies.signals import compute_bottom_fishing_signal


class TestBottomFishing(unittest.TestCase):
    def test_compute_bottom_fishing_signal(self):
        sig = compute_bottom_fishing_signal(
            tech_symbol="sz159915",
            bond_symbol="sh511260",
            lookback_window=20,
            erp_threshold=0.05,
            bias_threshold=-0.035,
            take_profit=0.08,
            stop_loss=-0.035,
            confirmed=True
        )
        self.assertTrue(sig["valid"])
        self.assertIn("target_symbol", sig)
        self.assertIn("is_bottom_signal", sig)
        self.assertIn("erp_pct", sig)
        self.assertIn("tech_bias", sig)

    def test_run_bottom_fishing_strategy(self):
        df = run_bottom_fishing_strategy(
            tech_symbol="sz159915",
            bond_symbol="sh511260",
            lookback_window=20,
            start_time="2023-01-01",
            end_time="2024-12-31"
        )
        self.assertFalse(df.empty)
        self.assertIn("strategy_nav", df.columns)
        self.assertIn("tech_nav", df.columns)
        self.assertIn("bond_nav", df.columns)
        self.assertIn("drawdown", df.columns)
        trades = get_bottom_fishing_trades(df)
        self.assertIsInstance(trades, pd.DataFrame)

    def test_simulation_account_bottom_fishing(self):
        with tempfile.TemporaryDirectory() as td:
            store = SimulationStore(td)
            cfg = defaults("bottom_fishing")
            acc = store.create("测试抄底账户", 100000.0, "bottom_fishing", cfg, auto=True)
            self.assertEqual(acc["strategy_type"], "bottom_fishing")
            symbols = symbols_for(acc)
            self.assertIn("sz159915", symbols)
            self.assertIn("sh511260", symbols)
            plan = build_plan(store, acc["id"])
            self.assertTrue(plan["signal"]["valid"])
            self.assertIn(plan["signal"]["target_symbol"], ("sz159915", "sh511260"))
            self.assertGreaterEqual(len(plan["orders"]), 0)


if __name__ == "__main__":
    unittest.main()
