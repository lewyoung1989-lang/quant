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
import math
from zoneinfo import ZoneInfo
import pandas as pd
from data.sina_fetcher import fetch_sina_stock_kline
from data.realtime_fetcher import fetch_realtime_quotes

def compute_rotation_signal(
    tech_symbol="sz159915",
    def_symbol="sh512890",
    lookback_window=20,
    live_quotes=None,
    as_of=None
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
    now = as_of or datetime.datetime.now(ZoneInfo("Asia/Shanghai"))
    tech_df = fetch_sina_stock_kline(tech_symbol, datalen=max(60, lookback_window + 10))
    def_df = fetch_sina_stock_kline(def_symbol, datalen=max(60, lookback_window + 10))
    if tech_df.empty or def_df.empty:
        return {"valid": False, "error": "历史日线未取得，请更新数据后重试。"}

    # 剔除今天已被写入日线缓存的数据（严禁将今天重复计算两次）
    today_str = now.date().isoformat()
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
    if not all(math.isfinite(float(v)) and float(v) > 0 for v in (tech_price, def_price, tech_base_close, def_base_close)):
        return {"valid": False, "error": "行情或历史基准价格无效，不能生成轮动信号。"}

    # 3. 盘中动量计算: P(t, now) / Close(t-N) - 1
    tech_mom = (tech_price - tech_base_close) / tech_base_close
    def_mom = (def_price - def_base_close) / def_base_close

    # 4. 盘中均线计算: [Close(t-N+1) + ... + Close(t-1) + P(t, now)] / N
    past_closes = hist_tech.loc[common_hist[-(lookback_window - 1):], "close"].values
    if not all(math.isfinite(float(v)) and float(v) > 0 for v in past_closes):
        return {"valid": False, "error": "历史均线数据存在缺失或无效价格。"}
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
        "historical_asof": common_hist[-1].strftime("%Y-%m-%d"),
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


def compute_compound_rotation_signal(
    tech_symbol="sz159915",
    div_symbol="sh512890",
    bond_symbol="sh511260",
    lookback_window=20,
    use_bias_exit=True,
    tier_thresholds=(0.15, 0.18, 0.21, 0.25),
    tier_weights=(1.00, 0.75, 0.50, 0.30, 0.10),
    use_trend_filter=True,
    trend_filter_window=60,
    th_overheat=0.20,
    th_neutral=0.35,
    erp_delta=0.025,
    current_erp_w=None,
    live_quotes=None,
    as_of=None,
    confirmed=False
):
    """
    计算复合攻守轮动策略的实时或确认信号：
    1. 进攻判定：进攻标的绝对动量 > 0 且站上均线（若开启 MA60 则同时站上 MA60）且动量强于防守底仓标的；
    2. 超买止盈：持有进攻标的时，若偏离率 BIAS 处于超买区，按五档阶梯压降仓位；
    3. 全局防守：释放的防守仓位由 ERP 股债利差模型在防守底仓（如红利低波）与避险防守（如十年国债）间动态分配。
    """
    if live_quotes is None:
        live_quotes = fetch_realtime_quotes([tech_symbol, div_symbol, bond_symbol])

    tech_quote = live_quotes.get(tech_symbol.lower(), {})
    div_quote = live_quotes.get(div_symbol.lower(), {})
    bond_quote = live_quotes.get(bond_symbol.lower(), {})

    now = as_of or datetime.datetime.now(ZoneInfo("Asia/Shanghai"))
    warmup = max(60, lookback_window + 10, trend_filter_window + 10 if use_trend_filter else 0)

    tech_df = fetch_sina_stock_kline(tech_symbol, datalen=warmup + 30)
    div_df = fetch_sina_stock_kline(div_symbol, datalen=warmup + 30)
    bond_df = fetch_sina_stock_kline(bond_symbol, datalen=warmup + 30)

    if tech_df.empty or div_df.empty or bond_df.empty:
        return {"valid": False, "error": "历史日线数据未取得，请更新数据后重试。"}

    today_str = now.date().isoformat()
    hist_tech = tech_df[tech_df.index.strftime("%Y-%m-%d") < today_str]
    hist_div = div_df[div_df.index.strftime("%Y-%m-%d") < today_str]
    hist_bond = bond_df[bond_df.index.strftime("%Y-%m-%d") < today_str]

    common_hist = hist_tech.index.intersection(hist_div.index).intersection(hist_bond.index).sort_values()
    if len(common_hist) < max(lookback_window + 2, trend_filter_window + 2 if use_trend_filter else 0):
        return {"valid": False, "error": "历史重合交易日不足，暂无法计算复合轮动信号。"}

    # 确定价格序列
    if confirmed:
        tech_close_series = hist_tech.loc[common_hist, "close"].astype(float)
        div_close_series = hist_div.loc[common_hist, "close"].astype(float)
        tech_price = float(tech_close_series.iloc[-1])
        div_price = float(div_close_series.iloc[-1])
        bond_price = float(hist_bond.loc[common_hist, "close"].iloc[-1])
    else:
        tech_price = float(tech_quote.get("price") or hist_tech.loc[common_hist, "close"].iloc[-1])
        div_price = float(div_quote.get("price") or hist_div.loc[common_hist, "close"].iloc[-1])
        bond_price = float(bond_quote.get("price") or hist_bond.loc[common_hist, "close"].iloc[-1])
        tech_close_series = pd.concat([hist_tech.loc[common_hist, "close"].astype(float), pd.Series([tech_price], index=[now.date()])])
        div_close_series = pd.concat([hist_div.loc[common_hist, "close"].astype(float), pd.Series([div_price], index=[now.date()])])

    # 1. 动量与均线
    tech_base = float(tech_close_series.iloc[-1 - lookback_window])
    tech_mom = (tech_price - tech_base) / tech_base
    div_base = float(div_close_series.iloc[-1 - lookback_window])
    div_mom = (div_price - div_base) / div_base
    tech_ma = float(tech_close_series.iloc[-lookback_window:].mean())
    tech_bias = (tech_price - tech_ma) / tech_ma

    if use_trend_filter and trend_filter_window > 0:
        tech_ma_trend = float(tech_close_series.iloc[-trend_filter_window:].mean())
        cond_trend = tech_price > tech_ma_trend
    else:
        tech_ma_trend = tech_ma
        cond_trend = True

    cond_mom = tech_mom > 0
    cond_ma = tech_price > tech_ma
    cond_rel = tech_mom > div_mom
    is_attack = bool(cond_mom and cond_ma and cond_trend and cond_rel)

    # 2. 进攻仓位与超买五档止盈
    if is_attack:
        if use_bias_exit:
            t1, t2, t3, t4 = tier_thresholds
            w0, w1, w2, w3, w4 = tier_weights
            if tech_bias < t1:
                w_attack = w0
            elif tech_bias < t2:
                w_attack = w1
            elif tech_bias < t3:
                w_attack = w2
            elif tech_bias < t4:
                w_attack = w3
            else:
                w_attack = w4
        else:
            w_attack = 1.00
    else:
        w_attack = 0.00

    w_def = round(1.00 - w_attack, 4)

    # 3. ERP 股债利差估值接管防守仓位
    from strategies.dividend_lowvol_swing_backtest import compute_indicators, load_or_sync_data
    raw = compute_indicators(load_or_sync_data())
    raw = raw[raw.index.strftime("%Y-%m-%d") < now.date().isoformat()].dropna(subset=["close", "pe", "rate_10y", "erp"])
    if len(raw) < 60:
        return {"valid": False, "error": "ERP 历史数据不足 60 个交易日。"}

    baseline = raw.iloc[-1]
    pe = float(baseline["pe"]) if confirmed else float(baseline["pe"]) * div_price / float(baseline["close"])
    rate_10y = float(baseline["rate_10y"])
    if pe <= 0 or not math.isfinite(pe) or not math.isfinite(rate_10y):
        return {"valid": False, "error": "估值或国债收益率数据无效。"}
    erp = 100.0 / pe - rate_10y
    percentile = float(baseline["erp_pct"]) if confirmed else float(pd.concat([raw["erp"].iloc[-250:], pd.Series([erp])]).rank(pct=True).iloc[-1])

    th_mid = (th_overheat + th_neutral) / 2.0
    delta = float(erp_delta)
    if current_erp_w is not None:
        # 映射到四档最近档位 (0.00, 0.30, 0.70, 1.00)
        if current_erp_w <= 0.15:
            cur_tier = 0.00
        elif current_erp_w <= 0.50:
            cur_tier = 0.30
        elif current_erp_w <= 0.85:
            cur_tier = 0.70
        else:
            cur_tier = 1.00

        # 不对称保护性防抖状态转移 (2.5% 防抖)
        if cur_tier == 1.00:
            if percentile <= (th_neutral - delta):
                cur_tier = 0.70
        elif cur_tier == 0.70:
            if percentile >= th_neutral:  # 深度价值直接打满，零延迟抄底
                cur_tier = 1.00
            elif percentile <= (th_mid - delta):
                cur_tier = 0.30
        elif cur_tier == 0.30:
            if percentile >= (th_mid + delta):
                cur_tier = 0.70
            elif percentile <= th_overheat:  # 极值过热直接清仓，零延迟避险
                cur_tier = 0.00
        elif cur_tier == 0.00:
            if percentile >= (th_overheat + delta):  # 防假突破，有效确认后才建底仓
                cur_tier = 0.30
        erp_w = cur_tier
    else:
        # 无前序持仓状态时采用四档静态切分
        if percentile <= th_overheat:
            erp_w = 0.00
        elif percentile <= th_mid:
            erp_w = 0.30
        elif percentile <= th_neutral:
            erp_w = 0.70
        else:
            erp_w = 1.00

    if erp_w == 0.00:
        erp_band = "过热避险带"
    elif erp_w == 0.30:
        erp_band = "初级试探底仓带"
    elif erp_w == 0.70:
        erp_band = "稳健增配带"
    else:
        erp_band = "低估性价比带"

    tw_tech = round(w_attack, 4)
    tw_div = round(w_def * erp_w, 4)
    tw_bond = round(w_def * (1.00 - erp_w), 4)

    weights = {tech_symbol: tw_tech, div_symbol: tw_div, bond_symbol: tw_bond}

    # 状态文字描述
    if is_attack:
        if w_attack == 1.00:
            target_symbol = tech_symbol
            description = f"动量突破且站上生命线，未触发超买，目标全仓进攻持有 {tech_quote.get('name', tech_symbol)}。"
        else:
            target_symbol = tech_symbol
            pct_atk = int(round(tw_tech * 100))
            pct_def = int(round(w_def * 100))
            description = f"进攻标的触发 BIAS 极值超买 ({tech_bias*100:.1f}%)，阶梯降速至 {pct_atk}%；释放防守资金 {pct_def}% 由 ERP({percentile*100:.1f}%) 接管（红利 {int(tw_div*100)}% + 国债 {int(tw_bond*100)}%）。"
    else:
        if erp_w == 1.00:
            target_symbol = div_symbol
            description = f"动量未达进攻条件，全额转入防守；ERP 分位 {percentile*100:.1f}% 处于{erp_band}，目标配置 100% {div_quote.get('name', div_symbol)}。"
        elif erp_w == 0.70:
            target_symbol = div_symbol
            description = f"动量未达进攻条件，全额转入防守；ERP 分位 {percentile*100:.1f}% 处于{erp_band}（2.5%防抖），目标配置 70% {div_quote.get('name', div_symbol)} + 30% {bond_quote.get('name', bond_symbol)}。"
        elif erp_w == 0.30:
            target_symbol = bond_symbol if tw_bond > tw_div else div_symbol
            description = f"动量未达进攻条件，全额转入防守；ERP 分位 {percentile*100:.1f}% 处于{erp_band}（2.5%防抖），目标配置 30% {div_quote.get('name', div_symbol)} + 70% {bond_quote.get('name', bond_symbol)}。"
        elif erp_w == 0.50:
            target_symbol = div_symbol
            description = f"动量未达进攻条件，全额转入防守；ERP 分位 {percentile*100:.1f}% 处于{erp_band}，目标均衡配置 50% {div_quote.get('name', div_symbol)} + 50% {bond_quote.get('name', bond_symbol)}。"
        else:
            target_symbol = bond_symbol
            description = f"动量未达进攻条件，全额转入防守；ERP 分位 {percentile*100:.1f}% 处于{erp_band}，目标避险配置 100% {bond_quote.get('name', bond_symbol)}。"

    return {
        "valid": True,
        "historical_asof": common_hist[-1].strftime("%Y-%m-%d"),
        "target_symbol": target_symbol,
        "weight": 1.0,
        "weights": weights,
        "is_attack": is_attack,
        "tech_bias": tech_bias,
        "tech_ma": tech_ma,
        "tech_ma_trend": tech_ma_trend,
        "tech_mom": tech_mom,
        "div_mom": div_mom,
        "erp": erp,
        "erp_pct": percentile,
        "erp_band": erp_band,
        "erp_w": erp_w,
        "description": description,
        "tech": {
            "symbol": tech_symbol, "name": tech_quote.get("name", "进攻标的"),
            "price": tech_price, "mom": tech_mom, "ma": tech_ma, "bias": tech_bias,
            "weight": tw_tech
        },
        "div": {
            "symbol": div_symbol, "name": div_quote.get("name", "防守底仓"),
            "price": div_price, "mom": div_mom, "weight": tw_div
        },
        "bond": {
            "symbol": bond_symbol, "name": bond_quote.get("name", "避险防守"),
            "price": bond_price, "weight": tw_bond
        }
    }
