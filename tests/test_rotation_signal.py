"""Regression checks for configurable rotation history and invalid input."""
import datetime as dt
import unittest
from unittest.mock import patch

import pandas as pd

from strategies.signals import compute_rotation_signal


class RotationSignalTests(unittest.TestCase):
    def history(self):
        return pd.DataFrame({"close": [1 + i / 1000 for i in range(130)]}, index=pd.bdate_range(end="2026-10-16", periods=130))

    def test_120_day_period_fetches_enough_history_and_ignores_today(self):
        frame = self.history()
        with patch("strategies.signals.fetch_sina_stock_kline", return_value=frame) as fetch:
            sig = compute_rotation_signal("sh588380", "sh511010", 120, {"sh588380": {"price": 1.5}, "sh511010": {"price": 1.2}}, as_of=dt.datetime(2026, 10, 16, 14, 50))
        self.assertTrue(sig["valid"])
        self.assertEqual(sig["historical_asof"], "2026-10-15")
        self.assertTrue(all(call.kwargs["datalen"] >= 130 for call in fetch.call_args_list))
        self.assertEqual(sig["target_symbol"], "sh588380")

    def test_empty_history_does_not_return_tradeable_signal(self):
        with patch("strategies.signals.fetch_sina_stock_kline", return_value=pd.DataFrame()):
            sig = compute_rotation_signal(live_quotes={})
        self.assertFalse(sig["valid"])

    def test_nonfinite_live_price_is_invalid(self):
        with patch("strategies.signals.fetch_sina_stock_kline", return_value=self.history()):
            sig = compute_rotation_signal(live_quotes={"sz159915": {"price": float("nan")}}, as_of=dt.datetime(2026, 10, 16))
        self.assertFalse(sig["valid"])
