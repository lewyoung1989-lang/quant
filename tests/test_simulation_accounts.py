"""Run with .venv/bin/python -m unittest discover -s tests -v. No real accounts or network."""
import concurrent.futures
import datetime as dt
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.simulation_store import AccountError, SHANGHAI, SimulationStore, defaults
from services.simulation_service import build_plan, execute_plan, is_session, market_status, portfolio, quote_issues, sellable, worker_tick

AT = dt.datetime(2026, 10, 16, 14, 50, tzinfo=SHANGHAI)


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SimulationStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def account(self, name="研究账户", capital=100000, strategy="rotation", auto=False, fee=.0001):
        return self.store.create(name, capital, strategy, defaults(strategy), auto=auto, fee_rate=fee)

    def quotes(self, **overrides):
        return {s: {"price": overrides.get(s, p), "quote_time": AT.isoformat()} for s, p in {"sh588380": 1.327, "sh511010": 122.88, "sh512890": 1.219, "sh511260": 135.208}.items()}

    def signal(self, symbol="sh588380", weight=1):
        return {"valid": True, "target_symbol": symbol, "weight": weight, "historical_asof": "2026-10-15", "description": "单元测试信号"}

    def plan(self, a, q=None, signal=None, at=AT):
        return build_plan(self.store, a["id"], self.quotes() if q is None else q, at=at, signal=signal or self.signal())

    def execute(self, a, p, key="first", q=None, signal=None, at=AT, automatic=False):
        return execute_plan(self.store, a["id"], p["id"], key, quotes=self.quotes() if q is None else q, signal=signal or self.signal(), at=at, automatic=automatic)

    def test_erp_bond_two_leg_execution_and_cash_switch(self):
        a = self.store.create('国债防守', 100000, 'dividend_erp',
                              {**defaults('dividend_erp'), 'defensive_asset': 'sh511260'})
        sig = self.signal('sh512890', .5)
        p = self.plan(a, signal=sig)
        self.assertTrue(p['can_execute'], p['reasons'])
        self.assertEqual({o['symbol'] for o in p['orders']}, {'sh512890', 'sh511260'})
        self.execute(a, p, signal=sig)
        a = self.store.get(a['id'])
        self.assertGreaterEqual(a['cash_available'], 0)
        self.assertAlmostEqual(portfolio(a,self.quotes())['total'],100000-p['fees'],places=2)
        # T+0 bond sale funds more equity without liquidating the equity already held.
        full = self.signal('sh512890', 1)
        p = self.plan(a, signal=full)
        self.assertEqual([(o['action'],o['symbol']) for o in p['orders']], [('卖出','sh511260'),('买入','sh512890')])
        self.execute(a,p,key='full',signal=full)
        a = self.store.get(a['id'])
        p = self.plan(a,signal=self.signal('sh512890',0))
        self.assertFalse(p['can_execute'])
        self.assertTrue(any('T+1' in reason for reason in p['reasons']))

    def test_erp_bond_initial_defense_and_switch_to_cash(self):
        a = self.store.create('纯防守',100000,'dividend_erp',
                              {**defaults('dividend_erp'),'defensive_asset':'sh511260'})
        sig = self.signal('sh512890',0)
        p = self.plan(a,signal=sig)
        self.assertEqual([(o['action'],o['symbol']) for o in p['orders']],[('买入','sh511260')])
        self.execute(a,p,signal=sig)
        a=self.store.get(a['id'])
        self.store.configure(a['id'],a['revision'],a['name'],'dividend_erp',defaults('dividend_erp'),False,a['fee_rate'])
        p=self.plan(self.store.get(a['id']),signal=sig)
        self.assertEqual([(o['action'],o['symbol']) for o in p['orders']],[('卖出','sh511260')])
        self.assertTrue(p['can_execute'])

    def test_erp_defense_validation_and_legacy_default(self):
        legacy=defaults('dividend_erp');legacy.pop('defensive_asset')
        a=self.store.create('兼容',100000,'dividend_erp',legacy)
        self.assertEqual(a['parameters']['defensive_asset'],'cash')
        with self.assertRaises(AccountError):
            self.store.create('无效',100000,'dividend_erp',{**legacy,'defensive_asset':'bad'})

    def test_default_manual_and_unique_name(self):
        a = self.account()
        self.assertFalse(a["auto_trade"])
        self.assertEqual(a["cash_available"], 100000)
        with self.assertRaises(AccountError):
            self.account()

    def test_amount_boundaries_and_nan(self):
        for value in (0, -1, math.nan, math.inf, 999.99, 1000.001, 1e10):
            with self.subTest(value=value), self.assertRaises(AccountError):
                self.account(capital=value)

    def test_invalid_parameters_do_not_create(self):
        for config in ({**defaults("dividend_erp"), "threshold_low": .9}, {**defaults("dividend_erp"), "weight_low": .99}):
            with self.assertRaises(AccountError):
                self.store.create("无效", 100000, "dividend_erp", config)
        self.assertEqual(self.store.list_accounts(), [])

    def test_transfer_preserves_pnl_and_is_idempotent(self):
        a = self.account()
        self.store.transfer(a["id"], 1, 50000, request_id="fund")
        self.store.transfer(a["id"], 1, 50000, request_id="fund")
        b = self.store.get(a["id"])
        self.assertEqual(b["cash_available"], 150000)
        self.assertEqual(portfolio(b, self.quotes())["pnl"], 0)
        self.assertEqual(len(self.store.entries(a["id"], "fund")), 2)

    def test_receipt_cannot_be_reused_for_other_funds(self):
        a, b = self.account(), self.account("另一个账户")
        self.store.transfer(a["id"], 1, 10000, request_id="fund")
        with self.assertRaises(AccountError):
            self.store.transfer(a["id"], 2, 20000, request_id="fund")
        with self.assertRaises(AccountError):
            self.store.transfer(b["id"], 1, 10000, request_id="fund")

    def test_overwithdrawal_and_revision_conflict(self):
        a = self.account()
        with self.assertRaises(AccountError):
            self.store.transfer(a["id"], 1, 100001, withdraw=True)
        self.store.transfer(a["id"], 1, 1000)
        with self.assertRaises(AccountError):
            self.store.transfer(a["id"], 1, 1000)
        self.assertEqual(self.store.get(a["id"])["cash_available"], 101000)

    def test_calendar_holidays_weekends_and_unknown_year(self):
        self.assertFalse(is_session(dt.date(2026, 10, 1)))
        self.assertFalse(is_session(dt.date(2026, 10, 10)))
        self.assertFalse(is_session(dt.date(2026, 2, 23)))
        self.assertTrue(is_session(dt.date(2026, 10, 16)))
        self.assertIsNone(is_session(dt.date(2027, 1, 4)))

    def test_window_edges(self):
        self.assertFalse(market_status(AT.replace(minute=44))["ready"])
        self.assertTrue(market_status(AT.replace(minute=45))["ready"])
        self.assertTrue(market_status(AT.replace(minute=55, second=59))["ready"])
        self.assertFalse(market_status(AT.replace(minute=56))["ready"])

    def test_quote_timestamp_price_and_coherence(self):
        for change in ({"quote_time": "bad"}, {"quote_time": "2026-10-15 14:50:00"}, {"quote_time": "2026-10-16 14:51:00"}, {"price": math.nan}, {"price": 0}):
            q = self.quotes()
            q["sh588380"].update(change)
            self.assertTrue(quote_issues(q, ["sh588380", "sh511010"], AT))
        q = self.quotes()
        q["sh511010"]["quote_time"] = "2026-10-16 14:49:30"
        self.assertTrue(quote_issues(q, ["sh588380", "sh511010"], AT))

    def test_no_quotes_never_fakes_valuation_or_signal(self):
        a = self.account()
        p = self.plan(a, q={})
        self.assertFalse(p["can_execute"])
        self.assertIsNone(p["signal"])
        self.assertFalse(p["orders"])

    def test_old_history_blocks_execution(self):
        a = self.account()
        p = self.plan(a, signal={**self.signal(), "historical_asof": "2026-10-09"})
        self.assertFalse(p["can_execute"])
        self.assertIn("历史指标", "".join(p["reasons"]))

    def test_initial_execution_fees_cash_and_receipt(self):
        a = self.account()
        p = self.plan(a)
        self.assertTrue(p["can_execute"])
        first = self.execute(a, p)
        second = self.execute(a, p)
        b = self.store.get(a["id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(self.store.entries(a["id"], "trade")), 1)
        self.assertGreaterEqual(b["cash_available"], 0)
        self.assertAlmostEqual(portfolio(b, self.quotes())["total"], 100000 - first["fees"], places=2)
        self.assertFalse(self.plan(b)["orders"])

    def test_price_change_requires_review(self):
        a = self.account()
        p = self.plan(a)
        with self.assertRaises(AccountError):
            self.execute(a, p, q=self.quotes(sh588380=1.33))
        self.assertFalse(self.store.get(a["id"])["positions"])

    def test_pause_and_outside_window_block_execution(self):
        a = self.account()
        p = self.plan(a)
        with self.assertRaises(AccountError):
            self.execute(a, p, at=AT.replace(hour=13))
        self.store.set_running(a["id"], 1, False)
        self.assertFalse(self.plan(a)["can_execute"])
        with self.assertRaises(AccountError):
            self.execute(a, p)

    def test_t_plus_one_and_next_session_switch(self):
        a = self.account()
        self.execute(a, self.plan(a))
        b = self.store.get(a["id"])
        switched = self.plan(b, signal=self.signal("sh511010"))
        self.assertFalse(switched["can_execute"])
        self.assertIn("T+1", "".join(switched["reasons"]))
        monday = AT.replace(day=19)
        q = self.quotes()
        for v in q.values():
            v["quote_time"] = monday.isoformat()
        sig = {**self.signal("sh511010"), "historical_asof": "2026-10-16"}
        p = self.plan(b, q=q, signal=sig, at=monday)
        self.assertTrue(p["can_execute"])
        self.execute(b, p, key="next", q=q, signal=sig, at=monday)
        c = self.store.get(a["id"])
        self.assertEqual(c["positions"][0]["symbol"], "sh511010")
        self.assertEqual(len(self.store.entries(a["id"], "trade")), 3)

    def test_automatic_requires_opt_in(self):
        a = self.account()
        with self.assertRaises(AccountError):
            self.execute(a, self.plan(a), automatic=True)
        self.assertFalse(self.store.entries(a["id"], "trade"))

    def test_worker_only_executes_opted_in_and_once_per_day(self):
        manual = self.account()
        auto = self.account("自动账户", auto=True)
        with patch("services.simulation_service.now", return_value=AT), patch("services.simulation_service.fetch_quotes", return_value=self.quotes()), patch("services.simulation_service.strategy_signal", return_value=self.signal()):
            worker_tick(self.store)
            worker_tick(self.store)
        self.assertFalse(self.store.entries(manual["id"], "trade"))
        self.assertEqual(len(self.store.entries(auto["id"], "trade")), 1)
        self.assertEqual(self.store.metadata("worker")["status"], "运行中")

    def test_worker_does_not_fetch_or_trade_during_closed_day(self):
        a = self.account(auto=True)
        with patch("services.simulation_service.fetch_quotes") as fetch:
            worker_tick(self.store, at=AT.replace(day=17))
            fetch.assert_not_called()
        self.assertFalse(self.store.entries(a["id"], "trade"))

    def test_execute_rechecks_real_clock_inside_transaction(self):
        a = self.account()
        p = self.plan(a)
        with patch("services.simulation_service.now", side_effect=[AT, AT.replace(minute=56)]), self.assertRaises(AccountError):
            execute_plan(self.store, a["id"], p["id"], "clock-boundary", quotes=self.quotes(), signal=self.signal())
        self.assertFalse(self.store.entries(a["id"], "trade"))

    def test_erp_partial_allocation_keeps_cash_and_tracks_fees(self):
        a = self.account(strategy="dividend_erp")
        sig = self.signal("sh512890", .5)
        p = self.plan(a, signal=sig)
        result = self.execute(a, p, signal=sig)
        updated = self.store.get(a["id"])
        port = portfolio(updated, self.quotes())
        self.assertGreater(updated["cash_available"], 49000)
        self.assertAlmostEqual(port["pnl"], -result["fees"], places=2)
        self.assertLessEqual(port["weight"], .501)

    def test_concurrent_duplicate_submission_has_one_batch(self):
        a = self.account(auto=True)
        p = self.plan(a)
        def submit(_):
            try:
                return self.execute(a, p, key="same-auto", automatic=True)
            except AccountError:
                return None
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(submit, range(2)))
        self.assertTrue(any(r and r["success"] for r in results))
        self.assertEqual(len(self.store.entries(a["id"], "trade")), 1)

    def test_strategy_change_and_rename_preserve_positions(self):
        a = self.account()
        self.execute(a, self.plan(a))
        b = self.store.get(a["id"])
        self.store.configure(a["id"], b["revision"], "重命名红利3号", "dividend_erp", defaults("dividend_erp"), False, .0002)
        c = self.store.get(a["id"])
        self.assertEqual(c["positions"], b["positions"])
        self.assertEqual(c["id"], b["id"])
        self.assertEqual(c["strategy_type"], "dividend_erp")

    def test_zero_cash_does_not_restore_initial_capital(self):
        a = self.account()
        self.store.transfer(a["id"], 1, 100000, withdraw=True)
        p = self.plan(a)
        self.assertEqual(p["portfolio"]["total"], 0)
        self.assertFalse(p["can_execute"])
        self.assertIn("不足一手", "".join(p["reasons"]))

    def test_transaction_rolls_back_entire_trade_batch(self):
        a = self.account()
        p = self.plan(a)
        original = self.store.entry
        def fail(conn, account_id, kind, data, *args, **kwargs):
            original(conn, account_id, kind, data, *args, **kwargs)
            if kind == "trade":
                raise RuntimeError("simulate disk failure")
        with patch.object(self.store, "entry", side_effect=fail), self.assertRaises(RuntimeError):
            self.execute(a, p)
        self.assertEqual(self.store.get(a["id"])["cash_available"], 100000)
        self.assertFalse(self.store.get(a["id"])["positions"])
        self.assertFalse(self.store.entries(a["id"], "trade"))
        self.assertIsNone(self.store.receipt("first"))

    def test_legacy_migration_preserves_files_cash_and_explicit_strategy(self):
        with tempfile.TemporaryDirectory() as directory:
            old = {"红利3号但实为轮动": {"initial_capital": 100000, "cash_available": 25031.5, "holding_symbol": "sh512890", "holding_amount": 61500, "auto_trade": True},
                   "真实ERP": {"initial_capital": 100000, "cash_available": 1200, "holding_symbol": "sh512890", "holding_amount": 1000, "strategy_type": "dividend_erp"}}
            path = Path(directory) / "simulated_accounts.json"
            path.write_text(json.dumps(old))
            before = path.read_bytes()
            store = SimulationStore(directory)
            rows = store.list_accounts()
            self.assertEqual(rows[0]["strategy_type"], "rotation")
            self.assertEqual(rows[0]["cash_available"], 25031.5)
            self.assertEqual(rows[0]["positions"][0]["shares"], 61500)
            self.assertEqual(rows[1]["parameters"]["threshold_high"], .35)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(SimulationStore(directory).list_accounts()), 2)

    def test_bad_legacy_data_stops_without_partial_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "simulated_accounts.json"
            path.write_text(json.dumps({"first": {"cash_available": 1000}, "broken": {"cash_available": -1}}))
            with self.assertRaises(AccountError):
                SimulationStore(directory)
            import sqlite3
            with sqlite3.connect(str(Path(directory) / "simulation.sqlite3")) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
