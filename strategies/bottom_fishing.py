#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
极值反抽抄底策略引擎 (Extreme Reversal Bottom Fishing Strategy Engine)

核心投资逻辑：
1. 宏观避险极值滤镜：
   - 当红利低波 ERP 分位 <= 5.0% 时（避险资金抱团到极致，成长资产具备极高赔率），开启抄底雷达。
2. 创业板极值超跌与止跌形态确认：
   - 创业板 20 日偏离率 BIAS_20 <= -3.5%（价格严重偏离短期均线）；
   - 当日收出止跌阳线或平盘 (Close >= Open)，拒绝接下坠飞刀。
3. 闲置资金生息与满仓抄底：
   - 未触发抄底信号时，100% 仓位持有十年期国债 ETF (sh511260) 无风险生息；
   - 触发信号后，次日开盘以 100% 仓位买入创业板 ETF (sz159915)。
4. 止盈止损机制：
   - 反弹收盘重新站上 20 日均线 (MA20)，或单笔收益率 >= +8% 时全额止盈换回国债；
   - 亏损达到 -3.5% 时坚决止损换回国债避险。
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.append(".")
from data.etf_pool import ETF_POOL
from data.sina_fetcher import fetch_sina_stock_kline
from strategies.dividend_lowvol_swing_backtest import compute_indicators, load_or_sync_data

CACHE_DIR = Path("./data")


def run_bottom_fishing_strategy(
    tech_symbol="sz159915",
    bond_symbol="sh511260",
    lookback_window=20,
    erp_threshold=0.05,
    bias_threshold=-0.035,
    take_profit=0.08,
    stop_loss=-0.035,
    exit_ma20=True,
    require_bullish=True,
    start_time="2019-01-18",
    end_time=None,
    benchmark="sh000300",
    cost_rate=0.0003,
    **kwargs
):
    """
    极值反抽抄底策略完整回测撮合引擎
    """
    # 1. 加载红利低波 ERP 真值与国债利率数据
    raw_div_data = compute_indicators(load_or_sync_data())
    
    # 2. 加载创业板与国债日线数据
    tech_df = fetch_sina_stock_kline(tech_symbol, datalen=3500, start_date="2018-01-01")
    tech_df.index = pd.to_datetime(tech_df.index)
    
    bond_df = fetch_sina_stock_kline(bond_symbol, datalen=3500, start_date="2018-01-01")
    bond_df.index = pd.to_datetime(bond_df.index)
    
    bench_df = fetch_sina_stock_kline(benchmark, datalen=3500, start_date="2018-01-01")
    bench_df.index = pd.to_datetime(bench_df.index)

    # 3. 对齐重合交易日
    common_idx = raw_div_data.index.intersection(tech_df.index).intersection(bond_df.index).intersection(bench_df.index).sort_values()
    if start_time:
        common_idx = common_idx[common_idx >= pd.Timestamp(start_time)]
    if end_time:
        common_idx = common_idx[common_idx <= pd.Timestamp(end_time)]
        
    if len(common_idx) < lookback_window + 10:
        raise ValueError("数据不足以完成极值反抽抄底回测。")

    df = pd.DataFrame(index=common_idx)
    df["erp_pct"] = raw_div_data.loc[common_idx, "erp_pct"]
    df["pe"] = raw_div_data.loc[common_idx, "pe"]
    df["rate_10y"] = raw_div_data.loc[common_idx, "rate_10y"]
    
    df["tech_open"] = tech_df.loc[common_idx, "open"].astype(float)
    df["tech_high"] = tech_df.loc[common_idx, "high"].astype(float)
    df["tech_low"] = tech_df.loc[common_idx, "low"].astype(float)
    df["tech_close"] = tech_df.loc[common_idx, "close"].astype(float)
    df["tech_vol"] = tech_df.loc[common_idx, "volume"].astype(float)
    
    df["bond_open"] = bond_df.loc[common_idx, "open"].astype(float)
    df["bond_close"] = bond_df.loc[common_idx, "close"].astype(float)
    df["bench_close"] = bench_df.loc[common_idx, "close"].astype(float)

    # 计算均线与 BIAS 偏离率
    df["ma20"] = df["tech_close"].rolling(lookback_window).mean()
    df["bias20"] = (df["tech_close"] - df["ma20"]) / df["ma20"]
    df["is_bullish"] = df["tech_close"] >= df["tech_open"]

    # 4. 逐日回测模拟（次日开盘调仓）
    capital = 100000.0
    position = "bond" # 'bond' or 'tech'
    shares = 0
    entry_price = 0.0
    
    history = []
    trade_records = []
    
    for i in range(lookback_window, len(df)):
        dt_curr = common_idx[i]
        curr_row = df.iloc[i]
        prev_row = df.iloc[i - 1]
        
        tech_open_today = curr_row["tech_open"]
        bond_open_today = curr_row["bond_open"]
        tech_close_today = curr_row["tech_close"]
        bond_close_today = curr_row["bond_close"]
        bench_close_today = curr_row["bench_close"]
        
        # 信号基于前一日 T-1 收盘
        p_erp = prev_row["erp_pct"]
        p_bias = prev_row["bias20"]
        p_bullish = prev_row["is_bullish"]
        
        buy_signal = (p_erp <= erp_threshold) and (p_bias <= bias_threshold) and (p_bullish if require_bullish else True)
        
        # 交易执行
        if position == "bond":
            if buy_signal:
                # 卖出国债，买入创业板
                cap_after_sell = (shares * bond_open_today * (1.0 - cost_rate)) if shares > 0 else capital
                entry_price = tech_open_today
                shares = (cap_after_sell * (1.0 - cost_rate)) / entry_price
                capital = 0.0
                position = "tech"
                trade_records.append({
                    "date": dt_curr.strftime("%Y-%m-%d"),
                    "action": f"买入 {tech_symbol}",
                    "symbol": tech_symbol,
                    "price": entry_price,
                    "reason": f"ERP分位 {p_erp*100:.1f}% <= {erp_threshold*100:.1f}%, 创业板BIAS {p_bias*100:.1f}%, 企稳收阳"
                })
            else:
                if shares == 0:
                    shares = (capital * (1.0 - cost_rate)) / bond_open_today
                    capital = 0.0
        elif position == "tech":
            curr_ret = (tech_open_today - entry_price) / entry_price
            exit_signal = False
            exit_reason = ""
            if curr_ret >= take_profit:
                exit_signal = True
                exit_reason = f"止盈达成 (+{curr_ret*100:.1f}%)"
            elif curr_ret <= stop_loss:
                exit_signal = True
                exit_reason = f"止损触发 ({curr_ret*100:.1f}%)"
            elif exit_ma20 and (prev_row["tech_close"] > prev_row["ma20"]):
                exit_signal = True
                exit_reason = f"反弹收复20日生命线 (+{curr_ret*100:.1f}%)"
                
            if exit_signal:
                cap_after_sell = shares * tech_open_today * (1.0 - cost_rate)
                shares = (cap_after_sell * (1.0 - cost_rate)) / bond_open_today
                position = "bond"
                trade_records.append({
                    "date": dt_curr.strftime("%Y-%m-%d"),
                    "action": f"卖出 {tech_symbol} 换国债",
                    "symbol": bond_symbol,
                    "price": tech_open_today,
                    "return": curr_ret,
                    "reason": exit_reason
                })

        nav = (shares * tech_close_today) if position == "tech" else (shares * bond_close_today)
        history.append({
            "date": dt_curr,
            "nav": nav,
            "position": position,
            "target_symbol": tech_symbol if position == "tech" else bond_symbol,
            "tech_close": tech_close_today,
            "bond_close": bond_close_today,
            "bench_close": bench_close_today,
            "erp_pct": curr_row["erp_pct"],
            "bias20": curr_row["bias20"]
        })

    res_df = pd.DataFrame(history).set_index("date")
    # 计算基准归一化净值
    res_df["strategy_nav"] = res_df["nav"] / res_df["nav"].iloc[0]
    res_df["tech_nav"] = res_df["tech_close"] / res_df["tech_close"].iloc[0]
    res_df["bond_nav"] = res_df["bond_close"] / res_df["bond_close"].iloc[0]
    res_df["bench_nav"] = res_df["bench_close"] / res_df["bench_close"].iloc[0]
    res_df["drawdown"] = (res_df["strategy_nav"] / res_df["strategy_nav"].cummax() - 1.0)
    
    res_df.attrs["trades"] = trade_records
    return res_df


def get_bottom_fishing_trades(df):
    trades = df.attrs.get("trades", [])
    if isinstance(trades, pd.DataFrame):
        return trades
    return pd.DataFrame(trades)


if __name__ == "__main__":
    df = run_bottom_fishing_strategy()
    print("回测完成，样本行数:", len(df))
    print("总收益:", f"{(df['strategy_nav'].iloc[-1]-1)*100:.2f}%")
    print("最大回撤:", f"{df['drawdown'].min()*100:.2f}%")
    print("交易笔数:", len(df.attrs["trades"]))
