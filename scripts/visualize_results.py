#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
量化回测结果可视化工具
读取 reports/backtest_daily_report.csv，生成策略净值、基准净值、超额收益 (Alpha)、回撤分析图表。
"""

import os
import pandas as pd
import matplotlib.pyplot as plt

os.environ["MPLCONFIGDIR"] = "/tmp/matplotlib"

def plot_backtest_report(csv_path="./reports/backtest_daily_report.csv", output_png="./reports/cumulative_return.png"):
    if not os.path.exists(csv_path):
        print(f"[-] 报告文件不存在: {csv_path}，请先执行回测。")
        return

    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    if "return" not in df.columns or "bench" not in df.columns:
        print("[-] CSV 文件缺少 return 或 bench 列")
        return

    # 计算累计收益率
    df["strat_cum"] = (1 + df["return"]).cumprod()
    df["bench_cum"] = (1 + df["bench"]).cumprod()
    df["excess_cum"] = df["strat_cum"] / df["bench_cum"]

    # 计算动态回撤
    df["strat_peak"] = df["strat_cum"].cummax()
    df["drawdown"] = (df["strat_cum"] - df["strat_peak"]) / df["strat_peak"]

    # 绘图
    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={'height_ratios': [3, 1]})

    # 上图：净值走势
    ax1.plot(df.index, df["strat_cum"], label="Strategy (LightGBM + Top30)", color="#e74c3c", linewidth=2)
    ax1.plot(df.index, df["bench_cum"], label="Benchmark (CSI 300)", color="#3498db", linestyle="--", linewidth=1.5)
    ax1.plot(df.index, df["excess_cum"], label="Excess Return (Alpha)", color="#2ecc71", linestyle=":", linewidth=1.5)
    ax1.set_ylabel("Cumulative NAV")
    ax1.set_title("A-Share Quantitative Strategy Backtest Performance", fontsize=14, fontweight="bold")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)

    # 下图：回撤走势
    ax2.fill_between(df.index, df["drawdown"], 0, color="#e74c3c", alpha=0.3, label="Drawdown")
    ax2.plot(df.index, df["drawdown"], color="#c0392b", linewidth=1)
    ax2.set_ylabel("Drawdown")
    ax2.set_xlabel("Date")
    ax2.legend(loc="lower left")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_png, dpi=200)
    print(f"[✓] 回测绩效图表已生成: {output_png}")

if __name__ == "__main__":
    plot_backtest_report()
