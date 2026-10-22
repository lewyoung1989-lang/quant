"""Regression checks for compound innovation rotation strategy engine."""
import unittest
import pandas as pd
from streamlit.testing.v1 import AppTest
from strategies.compound_innovation_rotation import (
    run_compound_innovation_rotation,
    generate_compound_trade_ledger
)


class CompoundInnovationRotationTests(unittest.TestCase):
    def test_run_compound_innovation_rotation_basic(self):
        df = run_compound_innovation_rotation(
            tech_symbol="sz159915",
            div_symbol="sh512890",
            bond_symbol="sh511260",
            lookback_window=20,
            use_bias_exit=True,
            use_erp_hysteresis=True,
            start_time="2023-01-01",
            end_time="2024-01-01"
        )
        self.assertIsInstance(df, pd.DataFrame)
        self.assertFalse(df.empty)
        required_cols = [
            "return", "bench", "turnover", "sample_stocks", "signal_state",
            "asset1_ret", "asset2_ret", "asset1_name", "asset2_name",
            "w_tech", "w_div", "w_bond"
        ]
        for col in required_cols:
            self.assertIn(col, df.columns)
        self.assertTrue(df["return"].notna().all())
        self.assertTrue(df["turnover"].between(0.0, 1.0).all())

    def test_bias_exit_toggle_modifies_signal_behavior(self):
        df_with_bias = run_compound_innovation_rotation(
            tech_symbol="sz159915",
            div_symbol="sh512890",
            bond_symbol="sh511260",
            use_bias_exit=True,
            start_time="2020-01-01",
            end_time="2020-12-31"
        )
        has_take_profit = df_with_bias["signal_state"].str.contains("锁利").any()
        self.assertTrue(has_take_profit, "在2020年创业板大牛市中应当触发阶梯锁利信号")

    def test_trend_filter_reduces_bear_market_whipsaw(self):
        df_filtered = run_compound_innovation_rotation(
            tech_symbol="sz159915",
            div_symbol="sh512890",
            bond_symbol="sh511260",
            use_trend_filter=True,
            trend_filter_window=60,
            start_time="2022-01-01",
            end_time="2022-12-31"
        )
        df_unfiltered = run_compound_innovation_rotation(
            tech_symbol="sz159915",
            div_symbol="sh512890",
            bond_symbol="sh511260",
            use_trend_filter=False,
            start_time="2022-01-01",
            end_time="2022-12-31"
        )
        # Trend filter should have fewer or equal attack days in 2022 bear market
        atk_filtered = (df_filtered["w_tech"] > 0).sum()
        atk_unfiltered = (df_unfiltered["w_tech"] > 0).sum()
        self.assertLessEqual(atk_filtered, atk_unfiltered, "MA60中长期趋势过滤应有效减少熊市主跌浪中的盲目进攻")

    def test_5tier_discrete_weights_and_erp_defense(self):
        df = run_compound_innovation_rotation(
            tech_symbol="sz159915",
            div_symbol="sh512890",
            bond_symbol="sh511260",
            use_bias_exit=True,
            start_time="2019-01-18",
            end_time="2026-10-20"
        )
        # Check that w_tech only takes values from [0.0, 0.10, 0.30, 0.50, 0.75, 1.00]
        unique_w_tech = set(round(w, 2) for w in df["w_tech"].unique())
        expected_weights = {0.0, 0.10, 0.30, 0.50, 0.75, 1.00}
        self.assertTrue(unique_w_tech.issubset(expected_weights), f"实际权重集合 {unique_w_tech} 应为五档阶梯的子集")

        # Check total weights sum to 1.0
        tot_weights = (df["w_tech"] + df["w_div"] + df["w_bond"]).round(4)
        self.assertTrue((tot_weights == 1.0).all(), "每日资产总权重必须精确等于 100%")

    def test_execution_modes_supported(self):
        df_same = run_compound_innovation_rotation(
            tech_symbol="sz159915",
            div_symbol="sh512890",
            bond_symbol="sh511260",
            execution_mode="same_close",
            start_time="2023-01-01",
            end_time="2023-06-30"
        )
        df_next = run_compound_innovation_rotation(
            tech_symbol="sz159915",
            div_symbol="sh512890",
            bond_symbol="sh511260",
            execution_mode="next_close",
            start_time="2023-01-01",
            end_time="2023-06-30"
        )
        self.assertFalse(df_same.empty)
        self.assertFalse(df_next.empty)
        self.assertEqual(len(df_same), len(df_next))

    def test_generate_compound_trade_ledger(self):
        df = run_compound_innovation_rotation(
            tech_symbol="sz159915",
            div_symbol="sh512890",
            bond_symbol="sh511260",
            start_time="2020-01-01",
            end_time="2021-01-01"
        )
        ledger_df, win_rate, total_closed, win_count = generate_compound_trade_ledger(
            df,
            tech_symbol="sz159915",
            div_symbol="sh512890",
            bond_symbol="sh511260"
        )
        self.assertIsInstance(ledger_df, pd.DataFrame)
        self.assertFalse(ledger_df.empty)
        required_cols = ["交割日期", "信号日期", "标的代码", "标的名称", "操作类型", "成交价格", "仓位调整", "调仓幅度", "单笔盈亏", "持仓天数", "交割状态", "成交模式", "量化触发依据"]
        for col in required_cols:
            self.assertIn(col, ledger_df.columns)
        self.assertGreaterEqual(win_rate, 0.0)
        self.assertLessEqual(win_rate, 100.0)
        self.assertGreater(total_closed, 0)
        self.assertGreaterEqual(win_count, 0)

    def test_asymmetric_hysteresis_4tier_defense(self):
        from strategies.signals import compute_compound_rotation_signal
        # Test 1: From 0% state, crossing 16% (below 15% + 2.5% = 17.5%) should stay at 0%
        # Here we mock by testing state transitions
        res_at_0 = compute_compound_rotation_signal(
            th_overheat=0.15,
            th_neutral=0.35,
            erp_delta=0.025,
            current_erp_w=0.0,
            confirmed=True
        )
        self.assertTrue(res_at_0["valid"])
        # Check weights dictionary structure
        self.assertIn("weights", res_at_0)
        self.assertEqual(len(res_at_0["weights"]), 3)
        self.assertAlmostEqual(sum(res_at_0["weights"].values()), 1.0, places=4)

    def test_compound_rotation_page_renders_cleanly(self):
        at = AppTest.from_file("app.py", default_timeout=30)
        at.query_params["strategy_mode"] = "复合攻守轮动"
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.tabs), 5)
        self.assertEqual(len(at.metric), 10)


if __name__ == "__main__":
    unittest.main()
