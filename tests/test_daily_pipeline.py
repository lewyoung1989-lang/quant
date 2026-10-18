import datetime as dt
import tempfile
import unittest
import numpy as np
from unittest.mock import patch
from services.daily_pipeline import target_day, tick
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
        self.assertEqual(target_day(AT.replace(hour=16, minute=29)), '2026-10-16')
        self.assertEqual(target_day(AT.replace(hour=16, minute=30)), '2026-10-19')
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

    def test_failure_retries_after_delay(self):
        calls = []
        def update(resource, day):
            calls.append(resource)
            raise RuntimeError('provider unavailable')
        self.assertFalse(tick(self.store, AT, update)['ready'])
        count = len(calls)
        tick(self.store, AT + dt.timedelta(minutes=1), update)
        self.assertEqual(len(calls), count)
        tick(self.store, AT + dt.timedelta(minutes=16), update)
        self.assertEqual(len(calls), count * 2)

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
