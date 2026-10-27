import datetime as dt
import tempfile
import unittest
from pathlib import Path
import numpy as np
from unittest.mock import patch
from services.daily_pipeline import target_day, tick, register_research_symbols, request_sync
from services.simulation_store import SimulationStore, SHANGHAI, defaults

AT = dt.datetime(2026, 10, 19, 10, tzinfo=SHANGHAI)

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SimulationStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_target_sessions(self):
        self.assertEqual(target_day(AT), '2026-10-16')
        self.assertEqual(target_day(AT.replace(day=18)), '2026-10-16')
        self.assertEqual(target_day(AT.replace(hour=20, minute=9, second=59)), '2026-10-16')
        self.assertEqual(target_day(AT.replace(hour=20, minute=10)), '2026-10-19')
        self.assertEqual(target_day(AT.replace(hour=14, minute=59), manual=True), '2026-10-16')
        self.assertEqual(target_day(AT.replace(hour=15, minute=0), manual=True), '2026-10-19')
        self.assertEqual(target_day(AT.replace(day=18, hour=16), manual=True), '2026-10-16')
        with patch('services.daily_pipeline.is_session', return_value=None):
            with self.assertRaises(ValueError): target_day(AT)

    @patch('services.daily_pipeline.fetch_quotes', return_value={})
    def test_success_skips_completed_downloads(self, quotes):
        calls = []
        def update(resource, day):
            calls.append(resource)
            return {'asof': day}
        self.assertTrue(tick(self.store, AT, update)['ready'])
        count = len(calls)
        self.assertGreaterEqual(count, 5)
        self.assertTrue(tick(self.store, AT + dt.timedelta(minutes=1), update)['ready'])
        self.assertEqual(len(calls), count)
        self.assertTrue(tick(self.store, AT + dt.timedelta(minutes=2), update, force=True)['ready'])
        self.assertEqual(len(calls), count)

    def test_failure_retries_after_delay(self):
        calls = []
        def update(resource, day):
            calls.append(resource)
            raise RuntimeError('provider unavailable')
        self.assertFalse(tick(self.store, AT, update)['ready'])
        count = len(calls)
        tick(self.store, AT + dt.timedelta(minutes=1), update)
        self.assertEqual(len(calls), count)
        tick(self.store, AT + dt.timedelta(minutes=21), update)
        self.assertEqual(len(calls), count * 2)

    @patch('services.daily_pipeline.fetch_quotes', return_value={})
    def test_manual_sync_bypasses_backoff_and_never_rolls_back_after_close(self, quotes):
        at = AT.replace(hour=15, minute=1)
        tick(self.store, at, lambda r, d: (_ for _ in ()).throw(RuntimeError('offline')), force=True)
        calls = []
        def update(resource, day):
            calls.append((resource, day))
            return {'asof': day}
        state = tick(self.store, at, update, force=True)
        self.assertTrue(state['ready'])
        self.assertEqual(state['data_asof'], '2026-10-19')
        self.assertTrue(all(day == '2026-10-19' for _, day in calls))
        count = len(calls)
        self.assertTrue(tick(self.store, at + dt.timedelta(minutes=1), update)['ready'])
        self.assertEqual(len(calls), count)

    @patch('services.daily_pipeline.fetch_quotes', return_value={})
    def test_selected_research_assets_are_downloaded(self, quotes):
        register_research_symbols(self.store, '复合攻守轮动', ['SH510300', 'sh511090'])
        calls = []
        tick(self.store, AT, lambda r, d: (calls.append(r) or {'asof': d}))
        self.assertIn('price:sh510300', calls)
        self.assertIn('price:sh511090', calls)

    @patch('services.daily_pipeline.subprocess.Popen')
    def test_sync_request_is_async_deduplicated_and_profile_scoped(self, popen):
        before = self.store.list_accounts()
        request_sync(self.store)
        request_sync(self.store)
        self.assertEqual(popen.call_count, 1)
        self.assertIn('--profile-dir', popen.call_args.args[0])
        self.assertIn(str(Path(self.tmp.name).resolve()), popen.call_args.args[0])
        self.assertEqual(before, self.store.list_accounts())

    @patch('services.daily_pipeline.fetch_quotes', side_effect=RuntimeError('offline'))
    def test_signal_network_failure_is_visible(self, quotes):
        account = self.store.create('test', 100000, 'dividend_erp', defaults('dividend_erp'))
        state = tick(self.store, AT, lambda r, d: {'asof': d})
        self.assertTrue(state['ready'])
        self.assertEqual(state['signals'][account['id']]['status'], '失败')
        self.assertIsNone(state['signals_signature'])

    @patch('services.daily_pipeline.fetch_quotes', return_value={})
    @patch('services.daily_pipeline.strategy_signal', return_value={'valid': np.bool_(True), 'historical_asof': '2026-10-16', 'weight': np.float64(.5)})
    def test_changed_parameters_regenerate_signals(self, signal, quotes):
        account = self.store.create('test', 100000, 'dividend_erp', defaults('dividend_erp'))
        tick(self.store, AT, lambda r, d: {'asof': d})
        changed = dict(account, settings_version=account['settings_version'] + 1,
                       parameters={**account['parameters'], 'threshold_low': .25})
        with patch.object(self.store, 'list_accounts', return_value=[changed]):
            state = tick(self.store, AT + dt.timedelta(minutes=1), lambda r, d: {'asof': d})
        self.assertEqual(signal.call_count, 2)
        self.assertEqual(state['signals'][account['id']]['parameters']['threshold_low'], .25)
