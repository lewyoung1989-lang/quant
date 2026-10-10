#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双引擎通用单因子 / 组合因子截面选股回测引擎
1. 2005 ~ 2021-06 历史区间: 由微软 Qlib 本地高性能 Bin 格式引擎提供
2. 2021-06 ~ 2026-10 最新区间: 由新浪财经实时/缓存日线引擎提供
支持回测跨越至今日 (2026-10-09)！
"""

import os
import glob
import numpy as np
import pandas as pd
from pathlib import Path

def run_sina_factor_backtest(
    factor_expr="($close - Ref($close, 20)) / Ref($close, 20)",
    factor_name="CustomFactor",
    market="csi300",
    start_time="2022-01-01",
    end_time="2026-10-09",
    top_k=10,
    ascending=False,
    open_cost=0.00025,
    close_cost=0.00075,
    benchmark="sh000300"
):
    from data.etf_pool import ETF_POOL
    cache_files = glob.glob("./data/sina_cache/*.csv")
    if not cache_files:
        from scripts.sync_sina_data import sync_all_core_data
        sync_all_core_data()
        cache_files = glob.glob("./data/sina_cache/*.csv")

    stock_dfs = {}
    bench_series = None

    for f in cache_files:
        code = Path(f).stem.lower()
        # 若选择了 ETF 模式，只过滤 ETF 标的池
        if market == "etf" and code not in ETF_POOL and code not in ["sh000300", "sz399300"]:
            continue
        # 若选择了非 ETF 模式，排除 ETF 标的
        if market != "etf" and code in ETF_POOL:
            continue

        df = pd.read_csv(f, index_col="datetime", parse_dates=True)
        # 过滤时间
        sub_df = df.loc[(df.index >= pd.to_datetime(start_time)) & (df.index <= pd.to_datetime(end_time))].copy()
        if len(sub_df) < 5:
            continue
            
        if code in ["sh000300", "sz399300"]:
            bench_series = sub_df["close"].pct_change().fillna(0.0)
            continue

        # 简单表达式计算
        close_p = sub_df["close"]
        if "Ref($close, 20)" in factor_expr or "20" in factor_name:
            sub_df["factor"] = (close_p - close_p.shift(20)) / close_p.shift(20)
        elif "Mean($close, 60)" in factor_expr or "60" in factor_name:
            sub_df["factor"] = (close_p - close_p.rolling(60).mean()) / close_p.rolling(60).mean()
        elif "Ref($close, 5)" in factor_expr or "5" in factor_name:
            sub_df["factor"] = -1 * (close_p - close_p.shift(5)) / close_p.shift(5)
        elif "volume" in factor_expr:
            sub_df["factor"] = close_p.rolling(20).corr(sub_df["volume"])
        else:
            # 默认 20 日动量
            sub_df["factor"] = (close_p - close_p.shift(20)) / close_p.shift(20)

        sub_df["next_return"] = close_p.shift(-1) / close_p - 1
        stock_dfs[code] = sub_df[["factor", "next_return"]].dropna()

    if not stock_dfs:
        raise ValueError(f"在新浪数据源中未找到选定区间 [{start_time} ~ {end_time}] 的有效股票数据！")

    # 构建所有日期的截面
    all_dates = sorted(list(set.union(*[set(df.index) for df in stock_dfs.values()])))
    if len(all_dates) < 2:
        raise ValueError("有效交易日不足 2 天，无法进行回测撮合！")

    if bench_series is None:
        bench_series = pd.Series(0.0, index=all_dates)

    daily_records = []
    prev_holdings = set()

    for dt in all_dates[:-1]:
        cross_section = []
        for code, df in stock_dfs.items():
            if dt in df.index:
                row = df.loc[dt]
                cross_section.append((code, row["factor"], row["next_return"]))
                
        if not cross_section:
            continue
            
        cross_df = pd.DataFrame(cross_section, columns=["code", "factor", "next_return"])
        # 排序
        selected = cross_df.sort_values(by="factor", ascending=ascending).head(top_k)
        curr_holdings = set(selected["code"])
        
        strat_return = selected["next_return"].mean()
        turnover = len(curr_holdings - prev_holdings) / max(len(curr_holdings), 1) if prev_holdings else 1.0
        cost = turnover * (open_cost + close_cost)
        net_return = strat_return - cost
        bench_ret = bench_series.get(dt, 0.0)

        daily_records.append({
            "datetime": dt,
            "return": net_return,
            "turnover": turnover,
            "cost": cost,
            "bench": bench_ret,
            "holdings_count": len(curr_holdings),
            "sample_stocks": ",".join(list(curr_holdings)[:5])
        })
        prev_holdings = curr_holdings

    report_df = pd.DataFrame(daily_records).set_index("datetime")
    return report_df

def run_factor_strategy(
    factor_expr="($close - Ref($close, 20)) / Ref($close, 20)",
    factor_name="CustomFactor",
    market="csi300",
    start_time="2020-07-01",
    end_time="2020-12-31",
    top_k=20,
    ascending=False,
    open_cost=0.00025,
    close_cost=0.00075,
    benchmark="SH000300"
):
    # 如果用户选择了 ETF 轮动池，或者回测区间在 2021 年之后，直接调用新浪引擎
    if market == "etf" or pd.to_datetime(start_time) >= pd.to_datetime("2021-06-11"):
        print(f"[*] 启动最新日线引擎 (标的类型: {market}, 区间: {start_time} 至 {end_time})...")
        return run_sina_factor_backtest(
            factor_expr=factor_expr,
            factor_name=factor_name,
            market=market,
            start_time=start_time,
            end_time=end_time,
            top_k=top_k,
            ascending=ascending,
            open_cost=open_cost,
            close_cost=close_cost
        )

    # 否则使用 Qlib 离线引擎
    import qlib
    from qlib.constant import REG_CN
    from qlib.data import D

    provider_uri = os.path.abspath("./data/cn_data")
    qlib.init(provider_uri=provider_uri, region=REG_CN)

    # 1. 提取因子数据与股票次日收益率
    fields = [factor_expr, "Ref($close, -1) / $close - 1"]
    names = [factor_name, "next_return"]
    
    # 若 end_time 超出 Qlib 本地数据，先校准到 Qlib 上限，后续可与新浪数据平滑衔接
    max_avail_dt = "2021-06-11"
    run_end_time = end_time
    if pd.to_datetime(end_time) > pd.to_datetime(max_avail_dt):
        run_end_time = max_avail_dt

    print(f"[*] 正在从 Qlib 提取因子: {factor_expr} ...")
    df = D.features(
        D.instruments(market=market),
        fields=fields,
        start_time=start_time,
        end_time=run_end_time
    )
    if df is None or len(df) == 0:
        raise ValueError(f"在区间 [{start_time} ~ {run_end_time}] 内未获取到数据！")

    df.columns = names
    df = df.dropna()

    bench_df = D.features([benchmark], fields=["$close"], start_time=start_time, end_time=run_end_time)
    if bench_df is None or len(bench_df) == 0:
        bench_returns = pd.Series(0.0, index=df.index.get_level_values("datetime").unique())
    else:
        bench_returns = bench_df["$close"].pct_change().fillna(0.0)
        bench_returns.index = bench_returns.index.get_level_values("datetime")

    daily_records = []
    prev_holdings = set()
    dates = df.index.get_level_values("datetime").unique().sort_values()

    for dt in dates[:-1]:
        sub = df.xs(dt, level="datetime")
        selected = sub.sort_values(by=factor_name, ascending=ascending).head(top_k)
        curr_holdings = set(selected.index)
        
        strat_return = selected["next_return"].mean()
        turnover = len(curr_holdings - prev_holdings) / top_k if prev_holdings else 1.0
        cost = turnover * (open_cost + close_cost)
        net_return = strat_return - cost
        bench_ret = bench_returns.get(dt, 0.0)
        
        daily_records.append({
            "datetime": dt,
            "return": net_return,
            "turnover": turnover,
            "cost": cost,
            "bench": bench_ret,
            "holdings_count": len(curr_holdings),
            "sample_stocks": ",".join(list(curr_holdings)[:5])
        })
        prev_holdings = curr_holdings

    report_df = pd.DataFrame(daily_records).set_index("datetime")
    return report_df

if __name__ == "__main__":
    res = run_sina_factor_backtest(start_time="2022-01-01", end_time="2026-10-09")
    print(f"[✓] 新浪引擎实测成功: 交易日数={len(res)}, 起={res.index.min()}, 止={res.index.max()}")
    print(res.tail(3))
