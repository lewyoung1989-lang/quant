#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双创指数与国债 ETF 攻守轮动策略引擎 (Twin-Innovation vs Treasury Bond Rotation Strategy)
投资逻辑：
- 进攻矛：双创50 / 科创50 / 创业板 (A股高Beta硬科技，反弹爆发力最强，但熊市回撤大)
- 防守盾：国债ETF / 10年期 / 30年期国债 (无风险资产，股债负相关，熊市避险生息)
- 轮动机制：
  1. 当双创具有绝对正动量 (Mom_N > 0) 且收盘价站上均线 (MA_N) 且动量强于国债：全仓买入双创，吃满主升浪；
  2. 当双创动量转负或跌破趋势线时：全额切换至国债 ETF 避险，避免深幅回撤并捕获债牛收益。
"""

import os
import sys
sys.path.append(".")
import pandas as pd
import numpy as np
from data.etf_pool import ETF_POOL
from data.sina_fetcher import fetch_sina_stock_kline

def run_twin_innovation_bond_rotation(
    tech_symbol="sh588380",       # 默认双创50ETF (可选 sh588000 科创50, sz159915 创业板)
    bond_symbol="sh511010",       # 默认国债ETF (可选 sh511260 十年债, sh511090 三十年债)
    lookback_window=20,          # 动量与趋势周期 (默认 20 日)
    start_time="2022-08-01",
    end_time="2026-10-09",
    benchmark="sh000300"
):
    # 1. 加载双创与国债行情 (支持长周期，自动获取全量数据)
    tech_df = fetch_sina_stock_kline(tech_symbol, datalen=4000, start_date=start_time)
    bond_df = fetch_sina_stock_kline(bond_symbol, datalen=4000, start_date=start_time)
    bench_df = fetch_sina_stock_kline(benchmark, datalen=4000, start_date=start_time)

    # 共同交易日
    common_idx = tech_df.index.intersection(bond_df.index)
    common_idx = common_idx[(common_idx >= pd.to_datetime(start_time)) & (common_idx <= pd.to_datetime(end_time))].sort_values()

    if len(common_idx) <= lookback_window:
        raise ValueError(f"有效重叠交易日不足 {lookback_window} 天，无法回测")

    tech_p = tech_df.loc[common_idx, "close"]
    bond_p = bond_df.loc[common_idx, "close"]

    # 基准
    if len(bench_df) > 0 and len(bench_df.index.intersection(common_idx)) > 0:
        bench_ret = bench_df.loc[common_idx, "close"].pct_change().fillna(0.0)
    else:
        bench_ret = pd.Series(0.0, index=common_idx)

    # 2. 计算动量与均线指标
    tech_mom = (tech_p - tech_p.shift(lookback_window)) / tech_p.shift(lookback_window)
    bond_mom = (bond_p - bond_p.shift(lookback_window)) / bond_p.shift(lookback_window)
    tech_ma = tech_p.rolling(lookback_window).mean()

    # 3. 逐日撮合生成持仓与收益率
    records = []
    prev_hold = None

    for i in range(lookback_window, len(common_idx) - 1):
        dt = common_idx[i]
        next_dt = common_idx[i + 1]

        t_m = tech_mom.loc[dt]
        b_m = bond_mom.loc[dt]
        t_price = tech_p.loc[dt]
        t_ma = tech_ma.loc[dt]

        # 计算各单一标的当天的日收益率 (Buy & Hold 纯持有)
        t_daily = (tech_p.loc[next_dt] - t_price) / t_price
        b_daily = (bond_p.loc[next_dt] - bond_p.loc[dt]) / bond_p.loc[dt]

        # 进攻信号：双创动量为正、站上均线、且动量强于国债
        if t_m > 0 and t_price > t_ma and t_m > b_m:
            cur_hold = tech_symbol
            daily_ret = t_daily
        else:
            cur_hold = bond_symbol
            daily_ret = b_daily

        # 换手率计算 (发生轮动时产生 100% 调仓换手，免印花税，仅万分之二佣金)
        if prev_hold is None:
            turnover = 1.0
            daily_ret -= 0.00025  # 开仓佣金
        elif prev_hold != cur_hold:
            turnover = 1.0
            daily_ret -= 0.0005   # 调仓卖出+买入双边费率
        else:
            turnover = 0.0

        b_ret = bench_ret.loc[next_dt] if next_dt in bench_ret.index else 0.0

        tech_name = ETF_POOL.get(tech_symbol, tech_symbol).split()[0]
        def_name = ETF_POOL.get(bond_symbol, bond_symbol).split()[0]

        records.append({
            "datetime": next_dt,
            "return": daily_ret,
            "bench": b_ret,
            "turnover": turnover,
            "sample_stocks": cur_hold,
            "signal_state": f"进攻【{tech_name}】🚀" if cur_hold == tech_symbol else f"防守【{def_name}】🛡️",
            "asset1_ret": t_daily,
            "asset2_ret": b_daily,
            "asset1_name": f"{tech_name}(纯持有)",
            "asset2_name": f"{def_name}(纯持有)"
        })
        prev_hold = cur_hold

    res_df = pd.DataFrame(records).set_index("datetime")
    res_df.sort_index(inplace=True)
    return res_df

if __name__ == "__main__":
    df = run_twin_innovation_bond_rotation()
    cum = (1 + df["return"]).cumprod().iloc[-1] - 1
    bench_cum = (1 + df["bench"]).cumprod().iloc[-1] - 1
    print(f"双创-国债轮动策略回测完成: 策略累计收益 {cum*100:.2f}%, 基准累计收益 {bench_cum*100:.2f}%")
