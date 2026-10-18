import unittest
import numpy as np
import pandas as pd
from strategies.dividend_lowvol_swing_backtest import run_simulation as engine, generate_trade_ledger


def simulate(data, **kwargs):
    kwargs.setdefault("defensive_asset", "bond")
    return engine(data, **kwargs)

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
    def test_open_execution_accounts_for_gap_and_intraday_return(self):
        raw = fixture([100, 120, 90], [.4, .1, .4])
        raw['open'] = [100, 110, 100]
        raw['bond_open'] = [100, 100, 100]
        r = simulate(raw, warmup=0, cost_rate=0, execution_price='open')
        # Buy after the overnight gap at 110; sell next open at 100.
        np.testing.assert_allclose(r.s2_erp_nav, [1, 120/110, 100/110])
        ledger, *_ = generate_trade_ledger(r, raw)
        self.assertEqual(ledger.loc[ledger['标的代码']=='512890.SH', '成交价格'].tolist(), [110, 100])
        self.assertAlmostEqual(r.s2_trade_return.iloc[2], 100/110-1)

    def test_open_bond_leg_and_fees(self):
        raw = fixture([100, 100, 100], [.1, .1, .1], [100, 120, 130])
        raw['open'] = [100]*3
        raw['bond_open'] = [100, 110, 125]
        r = simulate(raw, warmup=0, cost_rate=.01, execution_price='open')
        np.testing.assert_allclose(r.s2_erp_nav, [1, 120/110/1.01, 130/110/1.01])
        self.assertEqual(r.s2_turnover.iloc[2], 0)

    def test_same_close_uses_current_signal_but_old_units_earn_day_return(self):
        raw = fixture([100, 120, 90], [.1, .4, .1])
        r = simulate(raw, warmup=0, cost_rate=0, execution_price='same_close')
        np.testing.assert_allclose(r.s2_weight, [0, 1, 0])
        np.testing.assert_allclose(r.s2_erp_nav, [1, 1, .75])
        ledger, *_ = generate_trade_ledger(r, raw)
        self.assertEqual(ledger['信号日期'].tolist(), ledger['交割日期'].tolist())
        self.assertTrue(ledger['成交模式'].str.contains('理想化').all())
        self.assertTrue(ledger.loc[ledger['标的代码']=='512890.SH', '量化触发依据'].str.contains('当日最终收盘').all())

    def test_open_mode_rejects_missing_prices(self):
        with self.assertRaises(ValueError):
            simulate(fixture([100]*3, [.4]*3), warmup=0, execution_price='open')

    def test_cash_defense_no_bond_prices_or_bond_fees(self):
        raw = fixture([100, 100, 100, 100], [.4, .1, .1, .4])
        raw = raw.drop(columns='bond_close')
        raw['open'] = 100
        for mode in ['open', 'close', 'same_close']:
            r = engine(raw, warmup=0, execution_price=mode, cost_rate=.01)
            self.assertTrue(np.isfinite(r.s2_erp_nav).all())
            np.testing.assert_allclose(r.s2_erp_nav.diff().iloc[1:], -r.s2_fee.iloc[1:], atol=1e-12)
        r = engine(raw, warmup=0, execution_price='open', cost_rate=.01)
        np.testing.assert_allclose(r.s2_erp_nav, [1, 1/1.01, .99/1.01, .99/1.01])
        self.assertEqual(r.s2_fee.iloc[3], 0)

    def test_cash_stays_flat_during_full_defense(self):
        raw = fixture([100, 120, 90], [.1]*3, [100, 200, 300])
        r = engine(raw, warmup=0, cost_rate=.01)
        np.testing.assert_allclose(r.s2_erp_nav, 1)
        np.testing.assert_allclose(r.s2_fee, 0)

    def test_bond_ledger_includes_initial_defense_and_both_directions(self):
        raw = fixture([100]*5, [.1, .4, .1, .4, .1], [100, 110, 120, 130, 140])
        raw['open'] = 100
        raw['bond_open'] = [99, 105, 115, 125, 135]
        for mode in ['open', 'close', 'same_close']:
            r = engine(raw, warmup=0, execution_price=mode, defensive_asset='bond', cost_rate=.01)
            ledger, *_ = generate_trade_ledger(r, raw)
            bonds = ledger[ledger['标的代码']=='511260.SH']
            expected = r[r.s2_bond_delta.abs()>1e-14]
            self.assertEqual(len(bonds), len(expected))
            self.assertEqual(bonds['成交价格'].tolist(), expected.bond_execution_price.tolist())
            np.testing.assert_allclose(r.s2_fee, r.s2_equity_fee+r.s2_bond_fee)
            self.assertIn('防守买入', bonds['操作类型'].tolist())
            self.assertIn('防守卖出', bonds['操作类型'].tolist())
            sales=bonds[bonds['操作类型']=='防守卖出']
            self.assertTrue(sales.pnl_raw.notna().all())
            if mode != 'same_close':
                self.assertEqual(bonds.iloc[0]['仓位调整'], '0% ➔ 100%')
        cash = engine(raw, warmup=0, defensive_asset='cash')
        ledger, *_ = generate_trade_ledger(cash, raw)
        self.assertFalse((ledger['标的代码']=='511260.SH').any())

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
        self.assertAlmostEqual(ledger.loc[ledger["标的代码"]=="512890.SH"].iloc[-1].pnl_raw,128.7/cost-1)

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
        self.assertTrue(ledger[ledger["标的代码"]=="512890.SH"].empty)
        self.assertIn('pnl_raw',ledger.columns)
