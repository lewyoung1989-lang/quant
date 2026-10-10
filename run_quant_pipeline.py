#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化研究与模拟回测系统 - Qlib Pipeline
功能：
1. 初始化行情与因子特征库 (Alpha158)
2. 训练预测模型 (LightGBM)
3. 模拟撮合与策略回测 (Top-K 选股策略 + A股交易费率)
4. 输出策略综合评估报告 (年化、夏普、最大回撤、超额收益)
"""

import os
import sys
from pathlib import Path

os.environ["MPLCONFIGDIR"] = "/tmp/matplotlib"
import pandas as pd
import qlib
from qlib.constant import REG_CN
from qlib.utils import exists_qlib_data, init_instance_by_config
from qlib.workflow import R
from qlib.workflow.record_temp import SignalRecord, PortAnaRecord

def run_pipeline(
    data_path="./data/cn_data",
    market="csi300",
    train_start="2017-01-01",
    train_end="2019-12-31",
    valid_start="2020-01-01",
    valid_end="2020-06-30",
    test_start="2020-07-01",
    test_end="2020-12-31",
    top_k=30,
    n_drop=5,
    account_cash=1000000,
    open_cost=0.00025,       # 开仓佣金万 2.5
    close_cost=0.00075,      # 平仓佣金万 2.5 + 印花税千 0.5
    benchmark="SH000300"     # 沪深300基准
):
    print("=" * 60)
    print("【1. 系统初始化】连接 A 股数据引擎...")
    print("=" * 60)
    provider_uri = os.path.abspath(data_path)
    qlib.init(provider_uri=provider_uri, region=REG_CN)

    # 动态智能划分训练集与验证集，确保严谨递增、绝不重叠且不跨越测试集
    t_start_dt = pd.to_datetime(train_start)
    t_end_dt = pd.to_datetime(train_end)
    te_start_dt = pd.to_datetime(test_start)
    te_end_dt = pd.to_datetime(test_end)

    if t_end_dt >= te_start_dt:
        raise ValueError(f"训练结束日期 ({train_end}) 必须早于回测测试起始日期 ({test_start})！")

    # 训练集划分 80% 用于训练，后 20% 用于验证 early-stopping
    train_duration = (t_end_dt - t_start_dt).days
    valid_split_dt = t_start_dt + pd.Timedelta(days=int(train_duration * 0.8))
    
    seg_train_start = t_start_dt.strftime("%Y-%m-%d")
    seg_train_end = (valid_split_dt - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    seg_valid_start = valid_split_dt.strftime("%Y-%m-%d")
    seg_valid_end = t_end_dt.strftime("%Y-%m-%d")
    seg_test_start = te_start_dt.strftime("%Y-%m-%d")
    seg_test_end = te_end_dt.strftime("%Y-%m-%d")

    data_handler_config = {
        "start_time": seg_train_start,
        "end_time": seg_test_end,
        "fit_start_time": seg_train_start,
        "fit_end_time": seg_train_end,
        "instruments": market,
    }

    dataset_config = {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": {
                "class": "Alpha158",
                "module_path": "qlib.contrib.data.handler",
                "kwargs": data_handler_config,
            },
            "segments": {
                "train": (seg_train_start, seg_train_end),
                "valid": (seg_valid_start, seg_valid_end),
                "test": (seg_test_start, seg_test_end),
            },
        },
    }

    # 2. 预测模型配置 (LightGBM)
    model_config = {
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": {
            "loss": "mse",
            "colsample_bytree": 0.8879,
            "learning_rate": 0.0421,
            "subsample": 0.8789,
            "lambda_l1": 205.6999,
            "lambda_l2": 580.9768,
            "max_depth": 8,
            "num_leaves": 210,
            "num_threads": 4,
            "early_stopping_rounds": 50,
            "num_boost_round": 500,
        },
    }

    # 3. 回测策略与撮合规则配置
    port_analysis_config = {
        "strategy": {
            "class": "TopkDropoutStrategy",
            "module_path": "qlib.contrib.strategy",
            "kwargs": {
                "signal": "<PRED>",
                "topk": top_k,
                "n_drop": n_drop,
                "only_tradable": True,
            },
        },
        "backtest": {
            "start_time": test_start,
            "end_time": test_end,
            "account": account_cash,
            "benchmark": benchmark,
            "exchange_kwargs": {
                "freq": "day",
                "limit_threshold": 0.095,  # 接近涨跌停无法买卖限制 (A股 10% 涨跌停)
                "deal_price": "close",
                "open_cost": open_cost,
                "close_cost": close_cost,
                "min_cost": 5,             # A股最低 5 元手续费
            },
        },
    }

    print("\n" + "=" * 60)
    print("【2. 特征工程与模型训练】构建 Alpha158 因子并训练 LightGBM...")
    print(f"训练周期: {train_start} ~ {train_end}")
    print(f"验证周期: {valid_start} ~ {valid_end}")
    print(f"测试周期: {test_start} ~ {test_end}")
    print("=" * 60)

    model = init_instance_by_config(model_config)
    dataset = init_instance_by_config(dataset_config)

    # 启动 Qlib 实验管理工作流
    with R.start(experiment_name="A_Share_Alpha158_LGBM"):
        model.fit(dataset)
        R.save_objects(**{"params.pkl": model})

        print("\n" + "=" * 60)
        print("【3. 生成策略信号】计算模型选股预测评分...")
        print("=" * 60)
        # 记录预测信号
        recorder = R.get_recorder()
        sr = SignalRecord(model, dataset, recorder)
        sr.generate()

        print("\n" + "=" * 60)
        print("【4. 模拟撮合与回测执行】执行 Top-K 选股模拟交易...")
        print(f"持仓股票数: Top {top_k}")
        print(f"调仓淘汰数: {n_drop} 只/日")
        print(f"交易费率: 开仓万 {open_cost*10000:.1f}, 平仓万 {close_cost*10000:.1f}")
        print("=" * 60)
        # 运行模拟投资组合回测
        par = PortAnaRecord(recorder, port_analysis_config, "day")
        par.generate()

        # 提取回测结果分析
        report_df = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
        indicators_df = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")

    print("\n" + "=" * 60)
    print("【5. 回测绩效综合评估结果】")
    print("=" * 60)
    
    os.makedirs("./reports", exist_ok=True)
    report_csv_path = "./reports/backtest_daily_report.csv"
    report_df.to_csv(report_csv_path)
    print(f"[✓] 每日详细净值数据已保存至: {report_csv_path}")

    # 打印核心量化指标
    print("\n【组合表现与指标概览 (扣除交易手续费后)】:")
    if indicators_df is not None:
        print(indicators_df)
        indicators_df.to_csv("./reports/backtest_metrics.csv")
    
    print("\n【最近 10 个交易日净值走势片段】:")
    summary_cols = [c for c in ["return", "turnover", "cost", "bench"] if c in report_df.columns]
    print(report_df[summary_cols].tail(10))

    cum_return = (1 + report_df["return"]).cumprod().iloc[-1] - 1
    bench_cum_return = (1 + report_df["bench"]).cumprod().iloc[-1] - 1
    excess_return = (1 + report_df["return"]).cumprod().iloc[-1] / (1 + report_df["bench"]).cumprod().iloc[-1] - 1

    print("\n" + "-" * 40)
    print(f"策略累计总收益率:   {cum_return * 100:.2f}%")
    print(f"基准(沪深300)收益:  {bench_cum_return * 100:.2f}%")
    print(f"相对基准超额收益:   {excess_return * 100:.2f}%")
    print("-" * 40)

    # 自动生成可视化图表
    try:
        from scripts.visualize_results import plot_backtest_report
        plot_backtest_report(csv_path=report_csv_path, output_png="./reports/cumulative_return.png")
    except Exception as e:
        print(f"[-] 可视化生成跳过: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Qlib Quant Pipeline")
    parser.add_argument("--market", default="csi300", type=str)
    parser.add_argument("--benchmark", default="SH000300", type=str)
    parser.add_argument("--train_start", default="2017-01-01", type=str)
    parser.add_argument("--train_end", default="2019-12-31", type=str)
    parser.add_argument("--valid_start", default="2020-01-01", type=str)
    parser.add_argument("--valid_end", default="2020-06-30", type=str)
    parser.add_argument("--test_start", default="2020-07-01", type=str)
    parser.add_argument("--test_end", default="2020-12-31", type=str)
    parser.add_argument("--top_k", default=30, type=int)
    parser.add_argument("--n_drop", default=5, type=int)
    parser.add_argument("--open_cost", default=0.00025, type=float)
    parser.add_argument("--close_cost", default=0.00075, type=float)
    args = parser.parse_args()

    run_pipeline(
        market=args.market,
        benchmark=args.benchmark,
        train_start=args.train_start,
        train_end=args.train_end,
        valid_start=args.valid_start,
        valid_end=args.valid_end,
        test_start=args.test_start,
        test_end=args.test_end,
        top_k=args.top_k,
        n_drop=args.n_drop,
        open_cost=args.open_cost,
        close_cost=args.close_cost
    )
