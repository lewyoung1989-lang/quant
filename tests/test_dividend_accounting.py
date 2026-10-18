import unittest
import numpy as np
import pandas as pd
from strategies.dividend_lowvol_swing_backtest import run_simulation as simulate, generate_trade_ledger


def run_simulation(data, **kwargs):
    # Accounting regression fixtures explicitly retain their original allocations.
    kwargs.setdefault('w_overheat', .5)
    kwargs.setdefault('w_neutral', .75)
    return simulate(data, **kwargs)


def fixture(prices, erp, bonds=None):
    idx = pd.bdate_range('2026-09-01', periods=len(prices))
    return pd.DataFrame(dict(close=prices, bond_close=bonds or [100]*len(prices),
        csi300_close=[100]*len(prices), erp_pct=erp, ema30=prices,
        atr20=[1]*len(prices), bias20=[0]*len(prices), rsi14=[50]*len(prices)), index=idx)


class DividendAccountingTests(unittest.TestCase):
    def test_user_confirmed_default_allocations(self):
        r = simulate(fixture([100]*4, [.1,.3,.4,.4]), warmup=0, cost_rate=0)
        np.testing.assert_allclose(r.s2_weight, [0,0,.5,1])

    def test_previous_signal_close_execution_and_no_same_day_gain(self):
        raw = fixture([100, 200, 220], [.4, .3, .1])
        r = run_simulation(raw, warmup=0, cost_rate=0)
        np.testing.assert_allclose(r.s2_weight, [0, 1, .75])
        np.testing.assert_allclose(r.s2_erp_nav, [1, 1, 1.1])
        ledger, *_ = generate_trade_ledger(r, raw)
        self.assertEqual(ledger.iloc[0]['信号日期'], '2026-09-01')
        self.assertIn('40.0%', ledger.iloc[0]['量化触发依据'])
        self.assertIn('中性区', ledger.iloc[1]['量化触发依据'])

    def test_boundaries_and_custom_thresholds_recorded_in_report(self):
        raw = fixture([100]*5, [.2, .35, .351, .1, .4])
        r = run_simulation(raw, warmup=0, cost_rate=0)
        np.testing.assert_allclose(r.s2_weight, [0, .5, .75, 1, .5])
        r = run_simulation(raw, warmup=0, th_overheat=.25, th_neutral=.5)
        ledger, *_ = generate_trade_ledger(r, raw)
        self.assertIn('25%', ledger.iloc[0]['量化触发依据'])
        self.assertIn('50%', ledger.iloc[1]['量化触发依据'])

    def test_unchanged_target_keeps_units_instead_of_free_rebalancing(self):
        r = run_simulation(fixture([100,100,200,100],[.3]*4), warmup=0, cost_rate=0)
        np.testing.assert_allclose(r.s2_erp_nav, [1,1,1.75,1])
        self.assertAlmostEqual(r.s2_actual_weight.iloc[2], 1.5/1.75)
        self.assertEqual(r.s2_turnover.iloc[2], 0)

    def test_both_legs_and_initial_entry_pay_fees(self):
        r = run_simulation(fixture([100]*4,[.4,.1,.4,.4]),warmup=0,cost_rate=.01)
        first=1/1.01
        second=first*(1-.01)/(1-.01*.5+.01*.5)
        self.assertAlmostEqual(r.s2_erp_nav.iloc[1],first)
        self.assertAlmostEqual(r.s2_erp_nav.iloc[2],second)
        np.testing.assert_allclose(r.s2_erp_nav.diff().iloc[1:],-r.s2_fee.iloc[1:],atol=1e-12)

    def test_all_defensive_first_entry_earns_bond_after_execution(self):
        r=run_simulation(fixture([100]*3,[.1]*3,[100,200,220]),warmup=0,cost_rate=0,w_overheat=0)
        np.testing.assert_allclose(r.s2_erp_nav,[1,1,1.1])

    def test_sell_return_uses_weighted_cost_and_fees(self):
        raw=fixture([100,100,120,130],[.1,.4,.1,.1])
        r=run_simulation(raw,warmup=0,cost_rate=.01)
        units1=.5*(1/1.01)/100
        units2=r.s2_erp_nav.iloc[2]/120
        cost=(units1*101+(units2-units1)*121.2)/units2
        self.assertAlmostEqual(r.s2_trade_return.iloc[3],128.7/cost-1)
        ledger, *_=generate_trade_ledger(r,raw)
        self.assertAlmostEqual(ledger.iloc[-1].pnl_raw,128.7/cost-1)

    def test_future_signal_cannot_change_prior_nav(self):
        raw=fixture([100,105,95,110],[.4,.2,.3,.5])
        a=run_simulation(raw,warmup=0)
        raw.iloc[-1,raw.columns.get_loc('erp_pct')]=.01
        b=run_simulation(raw,warmup=0)
        pd.testing.assert_series_equal(a.s2_erp_nav,b.s2_erp_nav)

    def test_missing_indicator_rejected(self):
        raw=fixture([100,100],[.4,float('nan')])
        with self.assertRaises(ValueError):run_simulation(raw,warmup=0)

    def test_empty_ledger_retains_display_columns(self):
        raw=fixture([100,100],[.1,.1])
        r=run_simulation(raw,warmup=0,w_overheat=0)
        ledger,*_=generate_trade_ledger(r,raw)
        self.assertTrue(ledger.empty)
        self.assertIn('pnl_raw',ledger.columns)
