#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
纯量化信号判定服务 (Pure Signal Engine)
严防未来数据穿透，统一支持：
1. 盘中实时价格计算 (Intraday Preview)
2. 尾盘固定决策 (14:45~14:50 Final Decision)
3. 收盘复核与次日计划 (Post-Market Confirmation)
"""

import sys
sys.path.append(".")
import datetime
import pandas as pd
from data.sina_fetcher import fetch_sina_stock_kline
from data.realtime_fetcher import fetch_realtime_quotes

def compute_rotation_signal(
    tech_symbol="sz159915",
    def_symbol="sh512890",
    lookback_window=20,
    live_quotes=None
):
    """
    计算当前最新的轮动信号
    逻辑规则:
    1. 进攻动量 > 0
    2. 进攻价格 > 进攻均线
    3. 进攻动量 > 防守动量
    三者全部成立 => 进攻标的 (tech_symbol)
    任一不成立 => 防守标的 (def_symbol)

    :param tech_symbol: 进攻标的代码
    :param def_symbol: 防守标的代码
    :param lookback_window: 动量周期 N (默认 20 日)
    :param live_quotes: 实时报价字典，若为空则自动抓取最新实时行情
    :return: dict 包含目标标的、当前价格、动量值、均线值、满足条件详情、数据有效性
    """
    if live_quotes is None:
        live_quotes = fetch_realtime_quotes([tech_symbol, def_symbol])

    tech_quote = live_quotes.get(tech_symbol.lower(), {})
    def_quote = live_quotes.get(def_symbol.lower(), {})

    # 1. 加载历史日 K 线 (至少取 N+10 天已完结的历史日收盘)
    tech_df = fetch_sina_stock_kline(tech_symbol, datalen=60)
    def_df = fetch_sina_stock_kline(def_symbol, datalen=60)

    # 剔除今天已被写入日线缓存的数据（严禁将今天重复计算两次）
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    hist_tech = tech_df[tech_df.index.strftime("%Y-%m-%d") < today_str]
    hist_def = def_df[def_df.index.strftime("%Y-%m-%d") < today_str]

    # 取已完结交易日的交集
    common_hist = hist_tech.index.intersection(hist_def.index).sort_values()

    if len(common_hist) < lookback_window:
        return {
            "valid": False,
            "error": f"历史已完结交易日不足 {lookback_window} 天 (仅 {len(common_hist)} 天)",
            "target": def_symbol
        }

    # 2. 获取基准与实时价格
    tech_price = tech_quote.get("price") or hist_tech["close"].iloc[-1]
    def_price = def_quote.get("price") or hist_def["close"].iloc[-1]

    # N 天前的收盘价 (Close(t-N))
    tech_base_close = hist_tech.loc[common_hist[-lookback_window], "close"]
    def_base_close = hist_def.loc[common_hist[-lookback_window], "close"]

    # 3. 盘中动量计算: P(t, now) / Close(t-N) - 1
    tech_mom = (tech_price - tech_base_close) / tech_base_close
    def_mom = (def_price - def_base_close) / def_base_close

    # 4. 盘中均线计算: [Close(t-N+1) + ... + Close(t-1) + P(t, now)] / N
    past_closes = hist_tech.loc[common_hist[-(lookback_window - 1):], "close"].values
    tech_ma = (past_closes.sum() + tech_price) / lookback_window

    # 5. 三大进攻条件判别
    cond1 = tech_mom > 0.0                      # 绝对动量为正
    cond2 = tech_price > tech_ma                # 站上均线
    cond3 = tech_mom > def_mom                  # 相对动量优于防守标的

    is_attack = cond1 and cond2 and cond3
    target_symbol = tech_symbol if is_attack else def_symbol

    # 判定昨天（前一已收盘交易日）的信号，用于识别今日是否发生“新变盘”
    if len(common_hist) >= lookback_window + 1:
        prev_common = common_hist[:-1]
        yest_tech_close = hist_tech.loc[prev_common[-1], "close"]
        yest_def_close = hist_def.loc[prev_common[-1], "close"]
        yest_tech_base = hist_tech.loc[prev_common[-lookback_window], "close"]
        yest_def_base = hist_def.loc[prev_common[-lookback_window], "close"]

        yest_tech_mom = (yest_tech_close - yest_tech_base) / yest_tech_base
        yest_def_mom = (yest_def_close - yest_def_base) / yest_def_base
        yest_past_closes = hist_tech.loc[prev_common[-(lookback_window - 1):], "close"].values
        yest_tech_ma = (yest_past_closes.sum() + yest_tech_close) / lookback_window

        yest_is_attack = (yest_tech_mom > 0.0) and (yest_tech_close > yest_tech_ma) and (yest_tech_mom > yest_def_mom)
        is_new_signal = (is_attack != yest_is_attack)
        prev_target_symbol = tech_symbol if yest_is_attack else def_symbol
    else:
        is_new_signal = False
        prev_target_symbol = target_symbol

    now = datetime.datetime.now()
    # 判断当前时间窗口
    # 09:30-11:30, 13:00-15:00 为交易时段
    t_hour = now.hour
    t_min = now.minute
    
    is_decision_window = (t_hour == 14 and 45 <= t_min <= 55)
    is_after_market = (t_hour >= 15)

    if is_after_market:
        signal_type = "收盘确认计划 (次日执行)"
    elif is_decision_window:
        signal_type = "尾盘固定计划 (立即执行)"
    else:
        signal_type = "盘中实时预览 (尚未到尾盘决策窗)"

    return {
        "valid": True,
        "target_symbol": target_symbol,
        "is_attack": is_attack,
        "is_new_signal": is_new_signal,
        "prev_target_symbol": prev_target_symbol,
        "signal_type": signal_type,
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "tech": {
            "symbol": tech_symbol,
            "name": tech_quote.get("name", "进攻标的"),
            "price": tech_price,
            "mom": tech_mom,
            "ma": tech_ma,
            "base_close": tech_base_close,
            "quote_time": tech_quote.get("quote_time", "--"),
            "age_seconds": tech_quote.get("age_seconds", 0)
        },
        "defensive": {
            "symbol": def_symbol,
            "name": def_quote.get("name", "防守标的"),
            "price": def_price,
            "mom": def_mom,
            "base_close": def_base_close,
            "quote_time": def_quote.get("quote_time", "--"),
            "age_seconds": def_quote.get("age_seconds", 0)
        },
        "conditions": {
            "cond1_positive_mom": {
                "name": f"进攻标的绝对动量 > 0 ({tech_mom*100:+.2f}%)",
                "passed": bool(cond1)
            },
            "cond2_above_ma": {
                "name": f"进攻标的价格 > {lookback_window}日均线 (¥{tech_price:.3f} > ¥{tech_ma:.3f})",
                "passed": bool(cond2)
            },
            "cond3_mom_advantage": {
                "name": f"进攻动量强于防守动量 ({tech_mom*100:+.2f}% > {def_mom*100:+.2f}%)",
                "passed": bool(cond3)
            }
        }
    }

if __name__ == "__main__":
    sig = compute_rotation_signal("sz159915", "sh512890", 20)
    print("=== 量化轮动信号计算结果 ===")
    print(f"信号类型: {sig['signal_type']}")
    print(f"目标标的: {sig['target_symbol']} ({'🚀 全仓进攻' if sig['is_attack'] else '🛡️ 全仓防守'})")
    for k, v in sig['conditions'].items():
        print(f"  [{'✓' if v['passed'] else '✗'}] {v['name']}")
