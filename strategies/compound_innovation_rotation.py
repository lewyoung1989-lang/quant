#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
复合攻守轮动策略引擎 (Compound Innovation Momentum & Dividend ERP Rotation Engine)

核心投资逻辑（四大优化合一）：
1. 一层动量进攻：
   - 进攻标的 (默认 sz159915 创业板ETF)：当动量为正、价格站上短期均线且强于红利低波时触发进攻。
2. 进攻端五档阶梯超买止盈 (优化一)：
   - 当持有进攻标的时，若 20 日偏离率 BIAS 处于超买区，采用标准五档离散阶梯调仓 (100% -> 75% -> 50% -> 30% -> 10%)，告别断崖跳变；
3. 全局防守端统一由策略二 ERP 股债利差接管 (优化二与优化三)：
   - 任何情况下释放出来的防守仓位 (包括动量转弱清仓、超买阶段性降速)，全部交由策略二 ERP 股债利差模型在红利低波与十年国债 (sh511260) 之间动态自适应分配；
   - 引入 ±2% 滞后滤波带（Schmitt Trigger 逻辑），过滤 20%/35% 临界线频繁假信号磨损。
4. MA60 季度中长期趋势过滤 (优化四)：
   - 进攻触发增加中长期生命线过滤（要求价格同时站上 60 日均线），彻底杜绝熊市深跌期的弱反弹假突破磨损，有效压降历史最大回撤。
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.append(".")
from data.etf_pool import ETF_POOL
from data.sina_fetcher import fetch_sina_stock_kline

CACHE_DIR = Path("./data")

def run_compound_innovation_rotation(
    tech_symbol="sz159915",
    div_symbol="sh512890",
    bond_symbol="sh511260",
    lookback_window=20,
    use_bias_exit=True,
    tier_thresholds=(0.15, 0.18, 0.21, 0.25),
    tier_weights=(1.00, 0.75, 0.50, 0.30, 0.10),
    bias_take_profit=0.20,
    use_erp_hysteresis=True,
    use_trend_filter=True,
    trend_filter_window=60,
    execution_mode="same_close",
    th_overheat=0.20,
    th_neutral=0.35,
    erp_delta=0.025,
    start_time="2019-01-18",
    end_time="2026-10-20",
    benchmark="sh000300",
    cost_rate=0.0003,
    **kwargs
):
    # 1. 加载行情与估值数据
    tech_df = fetch_sina_stock_kline(tech_symbol, datalen=3500, start_date=start_time)
    div_df = fetch_sina_stock_kline(div_symbol, datalen=3500, start_date=start_time)
    bond_df = fetch_sina_stock_kline(bond_symbol, datalen=3500, start_date=start_time)
    bench_df = fetch_sina_stock_kline(benchmark, datalen=3500, start_date=start_time)

    idx_file = CACHE_DIR / "h30269_index_hist.csv"
    rate_file = CACHE_DIR / "bond_rates_hist.csv"

    if idx_file.exists():
        idx_df = pd.read_csv(idx_file, index_col=0, parse_dates=True)
    else:
        import akshare as ak
        idx_df = ak.stock_zh_index_hist_csindex(symbol="H30269", start_date="20190101", end_date="20261020")
        idx_df["日期"] = pd.to_datetime(idx_df["日期"])
        idx_df.set_index("日期", inplace=True)
        idx_df.to_csv(idx_file)

    if rate_file.exists():
        rates_df = pd.read_csv(rate_file, index_col=0, parse_dates=True)
    else:
        import akshare as ak
        rates_df = ak.bond_zh_us_rate()
        rates_df["日期"] = pd.to_datetime(rates_df["日期"])
        rates_df.set_index("日期", inplace=True)
        rates_df.to_csv(rate_file)

    # 共同交易日对齐
    common_idx = tech_df.index.intersection(div_df.index).intersection(bond_df.index).intersection(idx_df.index)
    start_dt = pd.to_datetime(start_time)
    end_dt = pd.to_datetime(end_time)
    common_idx = common_idx[(common_idx >= start_dt) & (common_idx <= end_dt)].sort_values()

    warmup_days = max(lookback_window, trend_filter_window if use_trend_filter else 0, 60)
    if len(common_idx) <= warmup_days + 10:
        raise ValueError(f"有效重叠交易日不足（至少需要 {warmup_days + 10} 天）")

    p_tech = tech_df.loc[common_idx, "close"].astype(float)
    p_div = div_df.loc[common_idx, "close"].astype(float)
    p_bond = bond_df.loc[common_idx, "close"].astype(float)

    if len(bench_df) > 0 and len(bench_df.index.intersection(common_idx)) > 0:
        bench_ret = bench_df.loc[common_idx, "close"].pct_change().fillna(0.0)
    else:
        bench_ret = pd.Series(0.0, index=common_idx)

    # 2. 动量与趋势指标
    tech_mom = (p_tech - p_tech.shift(lookback_window)) / p_tech.shift(lookback_window)
    div_mom = (p_div - p_div.shift(lookback_window)) / p_div.shift(lookback_window)
    tech_ma = p_tech.rolling(lookback_window).mean()
    tech_bias = (p_tech - tech_ma) / tech_ma

    # 进攻条件（结合中长期趋势过滤）
    if use_trend_filter and trend_filter_window > 0:
        tech_ma_trend = p_tech.rolling(trend_filter_window).mean()
        is_attack = (tech_mom > 0) & (p_tech > tech_ma) & (p_tech > tech_ma_trend) & (tech_mom > div_mom)
    else:
        tech_ma_trend = tech_ma
        is_attack = (tech_mom > 0) & (p_tech > tech_ma) & (tech_mom > div_mom)

    # 3. 红利低波 ERP 估值指标
    pe_series = idx_df.loc[common_idx, "滚动市盈率"].astype(float)
    rates_10y = rates_df["中国国债收益率10年"].dropna()
    rate_series = rates_10y.reindex(common_idx).ffill().bfill().astype(float)

    ey = (1.0 / pe_series) * 100.0
    erp = ey - rate_series
    erp_pct = erp.rolling(250, min_periods=60).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )

    # ERP 仓位映射 (支持滞后滤波防反复横跳)
    w_erp_list = []
    cur_w = 1.0
    for p in erp_pct:
        if np.isnan(p):
            w_erp_list.append(1.0)
            continue
        th_mid = (th_overheat + th_neutral) / 2.0
        delta = float(erp_delta)
        if use_erp_hysteresis:
            # 不对称保护性防抖状态转移 (2.5% 防抖)
            if cur_w == 1.00:
                if p <= (th_neutral - delta):
                    cur_w = 0.65
            elif cur_w == 0.65:
                if p >= th_neutral:  # 深度价值零延迟打满
                    cur_w = 1.00
                elif p <= (th_mid - delta):
                    cur_w = 0.35
            elif cur_w == 0.35:
                if p >= (th_mid + delta):
                    cur_w = 0.65
                elif p <= th_overheat:  # 极值过热零延迟避险
                    cur_w = 0.00
            elif cur_w == 0.00:
                if p >= (th_overheat + delta):  # 防假突破，确认后建仓
                    cur_w = 0.35
        else:
            if p <= th_overheat:
                cur_w = 0.00
            elif p <= th_mid:
                cur_w = 0.35
            elif p <= th_neutral:
                cur_w = 0.65
            else:
                cur_w = 1.00
        w_erp_list.append(cur_w)

    w_erp_series = pd.Series(w_erp_list, index=common_idx)

    # 4. 生成每日目标持仓权重与撮合
    warmup = max(lookback_window, trend_filter_window if use_trend_filter else 0, 60)
    valid_idx = common_idx[warmup:]

    records = []
    prev_tw = None

    tech_name = ETF_POOL.get(tech_symbol, tech_symbol).split()[0]
    div_name = ETF_POOL.get(div_symbol, div_symbol).split()[0]
    bond_name = ETF_POOL.get(bond_symbol, bond_symbol).split()[0]

    for i in range(len(valid_idx) - 1):
        dt = valid_idx[i]
        next_dt = valid_idx[i + 1]

        sig_dt = valid_idx[max(0, i - 1)] if execution_mode == "next_close" else dt
        attack = bool(is_attack.loc[sig_dt])
        bias = float(tech_bias.loc[sig_dt])
        erp_w = float(w_erp_series.loc[sig_dt])

        if attack:
            if use_bias_exit:
                t1, t2, t3, t4 = tier_thresholds
                w0, w1, w2, w3, w4 = tier_weights
                if bias < t1:
                    w_attack = w0
                elif bias < t2:
                    w_attack = w1
                elif bias < t3:
                    w_attack = w2
                elif bias < t4:
                    w_attack = w3
                else:
                    w_attack = w4
            else:
                w_attack = 1.00
        else:
            w_attack = 0.00

        # 全局防守资金统一交由策略二 ERP 股债利差模型动态接管
        w_def = 1.00 - w_attack
        tw_c = w_attack
        tw_d = w_def * erp_w
        tw_b = w_def * (1.00 - erp_w)

        if attack:
            if w_attack == 1.00:
                state_str = f"进攻【{tech_name} 100%】🚀"
            else:
                pct_atk = int(round(tw_c * 100))
                pct_def = int(round(w_def * 100))
                state_str = f"超买锁利【{tech_name} {pct_atk}% + 防守 {pct_def}%(ERP分配)】⚖️"
        else:
            if erp_w == 1.0:
                state_str = f"防守【{div_name} 100%】🛡️"
            elif erp_w == 0.65:
                state_str = f"防守【{div_name} 65% + {bond_name} 35%】⚖️"
            elif erp_w == 0.5:
                state_str = f"防守【{div_name} 50% + {bond_name} 50%】⚖️"
            elif erp_w == 0.35:
                state_str = f"防守【{div_name} 35% + {bond_name} 65%】🛡️"
            else:
                state_str = f"防守【{bond_name} 100%】🔒"

        r_c = (p_tech.loc[next_dt] - p_tech.loc[dt]) / p_tech.loc[dt]
        r_d = (p_div.loc[next_dt] - p_div.loc[dt]) / p_div.loc[dt]
        r_b = (p_bond.loc[next_dt] - p_bond.loc[dt]) / p_bond.loc[dt]

        gross_ret = tw_c * r_c + tw_d * r_d + tw_b * r_b

        if prev_tw is None:
            turnover = 1.0
            fee = 0.00025
        else:
            turnover = (abs(tw_c - prev_tw[0]) + abs(tw_d - prev_tw[1]) + abs(tw_b - prev_tw[2])) / 2.0
            fee = turnover * cost_rate

        daily_ret = gross_ret - fee
        prev_tw = (tw_c, tw_d, tw_b)

        primary_hold = tech_symbol if tw_c >= 0.5 else (div_symbol if tw_d >= tw_b else bond_symbol)
        b_ret = float(bench_ret.loc[next_dt]) if next_dt in bench_ret.index else 0.0

        records.append({
            "datetime": next_dt,
            "return": daily_ret,
            "bench": b_ret,
            "turnover": turnover,
            "sample_stocks": primary_hold,
            "signal_state": state_str,
            "asset1_ret": r_c,
            "asset2_ret": r_d,
            "asset3_ret": r_b,
            "asset1_name": f"{tech_name}(纯持有)",
            "asset2_name": f"{div_name}(纯持有)",
            "asset3_name": f"{bond_name}(纯持有)",
            "w_tech": tw_c,
            "w_div": tw_d,
            "w_bond": tw_b,
            "tech_close": float(p_tech.loc[next_dt]),
            "div_close": float(p_div.loc[next_dt]),
            "bond_close": float(p_bond.loc[next_dt]),
            "tech_ma": float(tech_ma.loc[sig_dt]) if pd.notna(tech_ma.loc[sig_dt]) else float(p_tech.loc[next_dt]),
            "tech_ma_trend": float(tech_ma_trend.loc[sig_dt]) if pd.notna(tech_ma_trend.loc[sig_dt]) else float(p_tech.loc[next_dt]),
            "tech_bias": float(tech_bias.loc[sig_dt]) if pd.notna(tech_bias.loc[sig_dt]) else 0.0,
            "erp_pct": float(erp_pct.loc[sig_dt]) if pd.notna(erp_pct.loc[sig_dt]) else 0.5,
            "signal_date": sig_dt,
            "execution_mode": execution_mode
        })

    res_df = pd.DataFrame(records).set_index("datetime")
    res_df.sort_index(inplace=True)
    return res_df


def generate_compound_trade_ledger(
    report_df: pd.DataFrame,
    tech_symbol: str = "sz159915",
    div_symbol: str = "sh512890",
    bond_symbol: str = "sh511260",
    bias_take_profit: float = 0.20,
    th_overheat: float = 0.20,
    th_neutral: float = 0.35,
    cost_rate: float = 0.0003
):
    """
    生成复合攻守轮动逐笔交易交割流水单 (Trade Ledger)
    包含各资产在动量进攻、极值锁利、红利估值低吸/过热避险各环节的买卖交割与单笔收益核算
    """
    ledger_columns = [
        "交割日期", "信号日期", "标的代码", "标的名称", "操作类型",
        "成交价格", "仓位调整", "调仓幅度", "单笔盈亏", "pnl_raw",
        "持仓天数", "交割状态", "成交模式", "量化触发依据"
    ]
    if report_df.empty:
        return pd.DataFrame(columns=ledger_columns), 0.0, 0, 0

    def _fmt_code(code: str) -> str:
        code_clean = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
        suffix = "SH" if code.lower().startswith("sh") else ("SZ" if code.lower().startswith("sz") else "BJ")
        return f"{code_clean}.{suffix}"

    tech_code = _fmt_code(tech_symbol)
    div_code = _fmt_code(div_symbol)
    bond_code = _fmt_code(bond_symbol)

    tech_name = ETF_POOL.get(tech_symbol, tech_symbol).split()[0]
    div_name = ETF_POOL.get(div_symbol, div_symbol).split()[0]
    bond_name = ETF_POOL.get(bond_symbol, bond_symbol).split()[0]

    records = []
    win_count = 0
    total_closed = 0

    # 跟踪买入均价与时间
    tech_buy_price = None
    tech_buy_date = None
    div_buy_price = None
    div_buy_date = None
    bond_buy_price = None
    bond_buy_date = None

    prev_w_tech = 0.0
    prev_w_div = 0.0
    prev_w_bond = 0.0

    # 首日初始化
    first_row = report_df.iloc[0]
    prev_w_tech = float(first_row.get("w_tech", 0.0))
    prev_w_div = float(first_row.get("w_div", 0.0))
    prev_w_bond = float(first_row.get("w_bond", 0.0))

    if prev_w_tech > 0:
        tech_buy_price = float(first_row.get("tech_close", 1.0))
        tech_buy_date = report_df.index[0]
    if prev_w_div > 0:
        div_buy_price = float(first_row.get("div_close", 1.0))
        div_buy_date = report_df.index[0]
    if prev_w_bond > 0:
        bond_buy_price = float(first_row.get("bond_close", 1.0))
        bond_buy_date = report_df.index[0]

    exec_mode_desc = "当日收盘成交（审慎基准）" if first_row.get("execution_mode") == "same_close" else "次日收盘成交（滞后对照）"

    for i in range(1, len(report_df)):
        row = report_df.iloc[i]
        dt = report_df.index[i]
        sig_dt = row.get("signal_date", dt)
        sig_str = pd.to_datetime(sig_dt).strftime("%Y-%m-%d") if pd.notna(sig_dt) else dt.strftime("%Y-%m-%d")
        dt_str = dt.strftime("%Y-%m-%d")

        cur_w_tech = float(row.get("w_tech", 0.0))
        cur_w_div = float(row.get("w_div", 0.0))
        cur_w_bond = float(row.get("w_bond", 0.0))

        diff_tech = cur_w_tech - prev_w_tech
        diff_div = cur_w_div - prev_w_div
        diff_bond = cur_w_bond - prev_w_bond

        bias_val = float(row.get("tech_bias", 0.0))
        erp_val = float(row.get("erp_pct", 0.5))

        # 1. 进攻标的变动 (Tech)
        if abs(diff_tech) >= 0.05:
            price = float(row.get("tech_close", 1.0))
            if diff_tech > 0:
                # 加仓/进攻
                tech_buy_price = price
                tech_buy_date = dt
                records.append({
                    "交割日期": dt_str,
                    "信号日期": sig_str,
                    "标的代码": tech_code,
                    "标的名称": tech_name,
                    "操作类型": "动量进攻加仓 🚀",
                    "成交价格": round(price, 3),
                    "仓位调整": f"{int(prev_w_tech*100)}% ➔ {int(cur_w_tech*100)}%",
                    "调仓幅度": f"{int(abs(diff_tech)*100)}%",
                    "单笔盈亏": "-",
                    "pnl_raw": np.nan,
                    "持仓天数": "-",
                    "交割状态": "建仓持股",
                    "成交模式": exec_mode_desc,
                    "量化触发依据": f"站上短期均线与中长趋势线且动量转正，强于红利低波 (BIAS={bias_val*100:+.1f}%)"
                })
            else:
                # 减仓/平仓
                hold_days = (dt - (tech_buy_date or dt)).days
                if tech_buy_price and tech_buy_price > 0:
                    pnl_raw = (price / tech_buy_price - 1.0) - 2 * cost_rate
                    pnl_str = f"{pnl_raw*100:+.2f}%"
                    status = "盈利 🟢" if pnl_raw > 0 else "亏损 🔴"
                    if pnl_raw > 0:
                        win_count += 1
                else:
                    pnl_raw = np.nan
                    pnl_str = "-"
                    status = "平仓"
                total_closed += 1

                if cur_w_tech > 0:
                    # 极值阶梯止盈锁利
                    action = "阶梯止盈锁利 ⚖️"
                    reason = f"20日偏离率 BIAS={bias_val*100:.1f}% 触发阶梯锁利，进攻仓降至{int(cur_w_tech*100)}%，防守资金由ERP动态接管"
                else:
                    # 退出进攻
                    action = "进攻平仓避险 🛡️"
                    reason = f"动量跌破均线/趋势线或弱于红利低波，退出进攻全面转入防守端"

                records.append({
                    "交割日期": dt_str,
                    "信号日期": sig_str,
                    "标的代码": tech_code,
                    "标的名称": tech_name,
                    "操作类型": action,
                    "成交价格": round(price, 3),
                    "仓位调整": f"{int(prev_w_tech*100)}% ➔ {int(cur_w_tech*100)}%",
                    "调仓幅度": f"{int(abs(diff_tech)*100)}%",
                    "单笔盈亏": pnl_str,
                    "pnl_raw": pnl_raw,
                    "持仓天数": f"{max(hold_days, 1)}天",
                    "交割状态": status,
                    "成交模式": exec_mode_desc,
                    "量化触发依据": reason
                })

        # 2. 防守底仓变动 (Div)
        if abs(diff_div) >= 0.05:
            price = float(row.get("div_close", 1.0))
            if diff_div > 0:
                div_buy_price = price
                div_buy_date = dt
                records.append({
                    "交割日期": dt_str,
                    "信号日期": sig_str,
                    "标的代码": div_code,
                    "标的名称": div_name,
                    "操作类型": "红利低估低吸 🛡️",
                    "成交价格": round(price, 3),
                    "仓位调整": f"{int(prev_w_div*100)}% ➔ {int(cur_w_div*100)}%",
                    "调仓幅度": f"{int(abs(diff_div)*100)}%",
                    "单笔盈亏": "-",
                    "pnl_raw": np.nan,
                    "持仓天数": "-",
                    "交割状态": "低估增配",
                    "成交模式": exec_mode_desc,
                    "量化触发依据": f"中证红利 ERP 分位={erp_val*100:.1f}% 进入低估吸纳区间，配置红利底仓"
                })
            else:
                hold_days = (dt - (div_buy_date or dt)).days
                if div_buy_price and div_buy_price > 0:
                    pnl_raw = (price / div_buy_price - 1.0) - 2 * cost_rate
                    pnl_str = f"{pnl_raw*100:+.2f}%"
                    status = "盈利 🟢" if pnl_raw > 0 else "亏损 🔴"
                    if pnl_raw > 0:
                        win_count += 1
                else:
                    pnl_raw = np.nan
                    pnl_str = "-"
                    status = "平仓"
                total_closed += 1

                reason = f"ERP 分位={erp_val*100:.1f}% 触碰过热线({th_overheat*100:.0f}%)或进攻启动切换"
                records.append({
                    "交割日期": dt_str,
                    "信号日期": sig_str,
                    "标的代码": div_code,
                    "标的名称": div_name,
                    "操作类型": "红利高抛避险 🔒",
                    "成交价格": round(price, 3),
                    "仓位调整": f"{int(prev_w_div*100)}% ➔ {int(cur_w_div*100)}%",
                    "调仓幅度": f"{int(abs(diff_div)*100)}%",
                    "单笔盈亏": pnl_str,
                    "pnl_raw": pnl_raw,
                    "持仓天数": f"{max(hold_days, 1)}天",
                    "交割状态": status,
                    "成交模式": exec_mode_desc,
                    "量化触发依据": reason
                })

        # 3. 避险资产变动 (Bond)
        if abs(diff_bond) >= 0.05:
            price = float(row.get("bond_close", 1.0))
            if diff_bond > 0:
                bond_buy_price = price
                bond_buy_date = dt
                records.append({
                    "交割日期": dt_str,
                    "信号日期": sig_str,
                    "标的代码": bond_code,
                    "标的名称": bond_name,
                    "操作类型": "国债避险配置 🔒",
                    "成交价格": round(price, 3),
                    "仓位调整": f"{int(prev_w_bond*100)}% ➔ {int(cur_w_bond*100)}%",
                    "调仓幅度": f"{int(abs(diff_bond)*100)}%",
                    "单笔盈亏": "-",
                    "pnl_raw": np.nan,
                    "持仓天数": "-",
                    "交割状态": "避险生息",
                    "成交模式": exec_mode_desc,
                    "量化触发依据": f"极值止盈或防守端根据 ERP 利差配置十年国债 ETF 避险生息"
                })
            else:
                hold_days = (dt - (bond_buy_date or dt)).days
                if bond_buy_price and bond_buy_price > 0:
                    pnl_raw = (price / bond_buy_price - 1.0) - 2 * cost_rate
                    pnl_str = f"{pnl_raw*100:+.2f}%"
                    status = "盈利 🟢" if pnl_raw > 0 else "亏损 🔴"
                    if pnl_raw > 0:
                        win_count += 1
                else:
                    pnl_raw = np.nan
                    pnl_str = "-"
                    status = "平仓"
                total_closed += 1

                records.append({
                    "交割日期": dt_str,
                    "信号日期": sig_str,
                    "标的代码": bond_code,
                    "标的名称": bond_name,
                    "操作类型": "国债调出切换 🔄",
                    "成交价格": round(price, 3),
                    "仓位调整": f"{int(prev_w_bond*100)}% ➔ {int(cur_w_bond*100)}%",
                    "调仓幅度": f"{int(abs(diff_bond)*100)}%",
                    "单笔盈亏": pnl_str,
                    "pnl_raw": pnl_raw,
                    "持仓天数": f"{max(hold_days, 1)}天",
                    "交割状态": status,
                    "成交模式": exec_mode_desc,
                    "量化触发依据": f"进攻机会出现或红利低波性价比凸显，国债资金转出配置权益端"
                })

        prev_w_tech = cur_w_tech
        prev_w_div = cur_w_div
        prev_w_bond = cur_w_bond

    ledger_df = pd.DataFrame(records)
    win_rate = (win_count / total_closed * 100.0) if total_closed > 0 else 0.0
    return ledger_df, win_rate, total_closed, win_count


if __name__ == "__main__":
    print("[*] 正在测试复合攻守轮动策略引擎...")
    df = run_compound_innovation_rotation()
    cum = (1 + df["return"]).cumprod().iloc[-1] - 1
    bench_cum = (1 + df["bench"]).cumprod().iloc[-1] - 1
    dd = ((1 + df["return"]).cumprod() - (1 + df["return"]).cumprod().cummax()) / (1 + df["return"]).cumprod().cummax()
    print(f"回测完成: 策略累计收益 {cum*100:.2f}%, 最大回撤 {dd.min()*100:.2f}%, 基准累计 {bench_cum*100:.2f}%")
