"""The latest full session must survive the provider's end-date boundary."""
import unittest
from unittest.mock import Mock, patch

from data.sina_fetcher import fetch_tencent_stock_kline


class HistoricalFetcherTests(unittest.TestCase):
    def test_inclusive_end_date_requests_next_day_and_excludes_future_rows(self):
        response = Mock()
        response.json.return_value = {'data': {'sh512890': {'qfqday': [
            ['2026-10-21', '1.21', '1.22', '1.23', '1.20', '100'],
            ['2026-10-22', '1.22', '1.23', '1.24', '1.21', '200'],
            ['2026-10-23', '1.23', '1.24', '1.25', '1.22', '300'],
        ]}}}
        session = Mock()
        session.get.return_value = response
        with patch('data.sina_fetcher.requests.Session', return_value=session):
            frame = fetch_tencent_stock_kline('sh512890', start_date='2026-10-21', end_date='2026-10-22')
        self.assertIn(',2026-10-23,640,qfq', session.get.call_args.args[0])
        self.assertEqual(frame.index[-1].date().isoformat(), '2026-10-22')
        self.assertEqual(len(frame), 2)
