#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化投研与模拟回测平台 Web UI (Streamlit)
支持：
1. AI 机器学习多因子策略 (LightGBM + Alpha158)
2. 因子实验室 (自定义表达式选股回测、经典指标库)
"""

import os
import sys
import subprocess
from pathlib import Path
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from strategies.custom_factors import CUSTOM_FACTORS
from strategies.factor_backtest import run_factor_strategy

# 页面基础配置
st.set_page_config(
    page_title="A股 AI 量化模拟回测平台",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 顶部导航
st.title("📈 A股 AI 量化模拟回测平台 (微软 Qlib)")
st.caption("集特征工程、因子实验室 (在线表达式)、AI 模型预测 (LightGBM) 与 A 股真实费率撮合")

# 侧边栏：策略模式选择
st.sidebar.title("🎛️ 策略模式选择")
st.sidebar.caption("💡 双引擎驱动: **Qlib 历史基准 (2005~2021) + 新浪财经直通最新至 2026-10-09**")
strategy_mode = st.sidebar.radio(
    "选择回测引擎模式:",
    [
        "⚡ 因子实验室 (自定义表达式 / 经典策略)",
        "🛡️ 双创与国债攻守轮动 (高胜率股债平衡)",
        "🤖 AI 机器学习多因子 (LightGBM + Alpha158)"
    ],
    index=1  # 默认推荐选择实战胜率极高的双创-国债轮动策略
)

universe_options = {
    "csi300": "沪深300股票池 (大盘核心)",
    "csi500": "中证500股票池 (中盘成长)",
    "etf": "📊 指数 ETF 核心轮动池 (300/500/1000/创业/科创/红利/黄金/纳指)"
}

market_display = st.sidebar.selectbox(
    "投资标的池 (Universe):",
    list(universe_options.values()),
    index=2  # 默认推荐选择 ETF 轮动池
)

# 反向找到 market key
market = [k for k, v in universe_options.items() if v == market_display][0]
benchmark = st.sidebar.text_input("基准标的 (Benchmark)", "SH000300")

if market == "etf" or strategy_mode == "🛡️ 双创与国债攻守轮动 (高胜率股债平衡)":
    st.sidebar.caption("💡 **ETF 费率优势**: A 股 ETF **免征千 0.5 印花税**且无过户费，仅需极低券商佣金！")
    default_open_cost = 1.0
    default_close_cost = 1.0
else:
    default_open_cost = 2.5
    default_close_cost = 7.5

st.sidebar.subheader("💸 交易费率设置")
open_cost_bp = st.sidebar.number_input("买入佣金 (‱ 万分之)", value=default_open_cost, step=0.5)
close_cost_bp = st.sidebar.number_input("卖出费率 (‱ 万分之)", value=default_close_cost, step=0.5, help="股票: 万2.5佣金+千0.5印花税=万7.5；ETF免印花税通常为万1")

REPORT_CSV = "./reports/backtest_daily_report.csv"
FACTOR_REPORT_CSV = "./reports/factor_backtest_report.csv"
TWIN_BOND_REPORT_CSV = "./reports/twin_bond_report.csv"

# ==========================================
# 模式一：因子实验室 (自定义表达式与经典技术选股)
# ==========================================
if strategy_mode == "⚡ 因子实验室 (自定义表达式 / 经典策略)":
    st.sidebar.subheader("🧪 因子与选股规则")
    
    preset_choice = st.sidebar.selectbox(
        "预置经典因子库:",
        ["[自定义手写表达式]"] + list(CUSTOM_FACTORS.keys())
    )

    if preset_choice == "[自定义手写表达式]":
        factor_expr = st.sidebar.text_area(
            "输入 Qlib 因子公式 (Expression):",
            value="($close - Ref($close, 20)) / Ref($close, 20)",
            help="支持算子: Mean($close, N), Ref($close, N), Std($close, N), Slope($close, N), Corr($close, $volume, N)"
        )
    else:
        factor_expr = CUSTOM_FACTORS[preset_choice]
        st.sidebar.code(factor_expr, language="python")

    direction = st.sidebar.radio("选股方向:", ["因子值最大优先 (动量/突破)", "因子值最小优先 (反转/低估)"])
    ascending = True if "最小" in direction else False

    if market == "etf":
        top_k = st.sidebar.slider("每日持仓 ETF 标的数 (Top-K)", min_value=1, max_value=5, value=2, step=1, help="ETF轮动通常集中持有最强的 1~2 只")
        def_start = pd.to_datetime("2022-01-01")
    else:
        top_k = st.sidebar.slider("每日持仓股票数 (Top-K)", min_value=5, max_value=50, value=20, step=5)
        def_start = pd.to_datetime("2020-07-01")
    
    date_range = st.sidebar.date_input(
        "回测时间区间:",
        [def_start, pd.to_datetime("2026-10-09")]
    )

    run_factor_btn = st.sidebar.button("🚀 运行因子选股回测", type="primary", use_container_width=True)

    # 快捷语法参考
    with st.expander("📖 查看 Qlib 表达式引擎常用语法说明"):
        st.markdown("""
        | 表达式语法 | 含义说明 | 典型量化策略应用 |
        | :--- | :--- | :--- |
        | `($close - Ref($close, 20)) / Ref($close, 20)` | 20 日收益动量 | 动量追涨策略 |
        | `($close - Mean($close, 60)) / Mean($close, 60)` | 60 日均线偏离率 (BIAS) | 突破 / 均线偏离策略 |
        | `-1 * ($close - Ref($close, 5)) / Ref($close, 5)` | 5 日跌幅最大 | 超跌反弹 / 反转策略 |
        | `Std($close / Ref($close, 1) - 1, 20)` | 20 日收益率波动率 | 低波动防守策略 |
        | `Corr($close, $volume, 20)` | 20 日量价相关系数 | 量价背离 / 量价齐升 |
        | `Slope($close, 10)` | 10 日线性回归斜率 | 趋势跟踪 |
        """)

    if run_factor_btn:
        if len(date_range) < 2:
            st.error("⚠️ 请在日历中选择完整的【开始日期】与【结束日期】（需点选两次）！")
        else:
            start_d = str(date_range[0])
            end_d = str(date_range[1])
            with st.spinner(f"正在执行因子 [{factor_expr}] 截面选股模拟撮合..."):
                try:
                    res_df = run_factor_strategy(
                        factor_expr=factor_expr,
                        factor_name=preset_choice if preset_choice != "[自定义手写表达式]" else "CustomFactor",
                        market=market,
                        start_time=start_d,
                        end_time=end_d,
                        top_k=top_k,
                        ascending=ascending,
                        open_cost=open_cost_bp / 10000,
                        close_cost=close_cost_bp / 10000,
                        benchmark=benchmark
                    )
                    os.makedirs("./reports", exist_ok=True)
                    res_df.to_csv(FACTOR_REPORT_CSV)
                    act_start = res_df.index.min().strftime('%Y-%m-%d')
                    act_end = res_df.index.max().strftime('%Y-%m-%d')
                    st.success(f"因子策略回测成功！实际撮合区间: {act_start} ~ {act_end} (共 {len(res_df)} 交易日)")
                except Exception as e:
                    st.error(f"因子回测失败: {e}")

    active_csv = FACTOR_REPORT_CSV if os.path.exists(FACTOR_REPORT_CSV) else None

# ==========================================
# 模式二：双创指数与国债 ETF 攻守轮动策略 (实战高胜率)
# ==========================================
elif strategy_mode == "🛡️ 双创与国债攻守轮动 (高胜率股债平衡)":
    from strategies.twin_innovation_bond_rotation import run_twin_innovation_bond_rotation

    st.sidebar.subheader("🎯 资产标的配置")
    tech_options = {
        "sz159915": "创业板ETF [2011年上市，成长爆发之矛，推荐配合红利低波]",
        "sh588380": "双创50ETF [2021年上市，中短周期硬科技龙头]",
        "sh588000": "科创50ETF [2020年上市，芯片与硬件龙头]"
    }
    bond_options = {
        "sh512890": "红利低波ETF 华泰柏瑞 [2019年上市，高股息低波动防守神器]",
        "sh510880": "红利ETF 华泰柏瑞 [2007年上市，超长历史经典高股息之盾]",
        "sh511010": "国债ETF 5年期 [2013年上市，无风险现金管理之盾]",
        "sh511260": "十年国债ETF [2018年上市，中长端利率债避险]",
        "sh511090": "三十年国债ETF [2023年上市，超长端高弹性债]"
    }

    selected_tech = st.sidebar.selectbox("🚀 进攻矛 (成长/双创标的):", list(tech_options.keys()), format_func=lambda x: tech_options[x], index=0)
    selected_bond = st.sidebar.selectbox("🛡️ 防守盾 (红利/国债标的):", list(bond_options.keys()), format_func=lambda x: bond_options[x], index=0)

    # 标的上市时间提醒
    if selected_bond == "sh512890":
        st.sidebar.caption("💡 **创业板 + 红利低波 华泰柏瑞**：成长风格与稳健高股息哑铃型完美轮动！(上市于 2019-01-18)")
    elif selected_bond == "sh510880":
        st.sidebar.caption("💡 **创业板 + 红利ETF 华泰柏瑞**：2007 年上市，支持 2013 年起超长历史完整牛熊回测！")
    elif selected_tech == "sh588380":
        st.sidebar.caption("ℹ️ 双创50ETF 上市于 2021-06-29，若需 2019/2013 年起超长回测请选【创业板ETF】。")
    elif selected_tech == "sh588000":
        st.sidebar.caption("ℹ️ 科创50ETF 上市于 2020-09-28，若需更长历史回测请选【创业板ETF】。")
    if selected_bond == "sh511090":
        st.sidebar.caption("⚠️ 三十年国债ETF 上市于 2023-06-13，选择该标的回测起点将锁定在 2023 年。")

    st.sidebar.subheader("📐 动量与趋势参数")
    lookback_window = st.sidebar.slider("动量与均线周期 (日):", min_value=5, max_value=60, value=20, step=5, help="经典20日周期：进攻标的20日动量>0且突破20日均线时全仓进攻，跌破时全额切换至防守标的")

    st.sidebar.subheader("📅 回测时间范围")
    # 根据用户选择智能设定推荐起始时间
    if selected_tech == "sz159915" and selected_bond in ["sh511010", "sh510880"]:
        default_start_val = pd.to_datetime("2013-08-01")
    elif selected_bond == "sh512890":
        default_start_val = pd.to_datetime("2019-02-25")
    else:
        default_start_val = pd.to_datetime("2022-08-01")

    start_date = st.sidebar.date_input("开始日期", default_start_val)
    end_date = st.sidebar.date_input("结束日期", pd.to_datetime("2026-10-09"))

    run_rotation_btn = st.sidebar.button("🚀 启动攻守轮动回测", type="primary", use_container_width=True)

    if run_rotation_btn:
        with st.spinner("正在基于实时数据执行成长进攻与防御盾牌动态攻守轮动撮合..."):
            try:
                res_df = run_twin_innovation_bond_rotation(
                    tech_symbol=selected_tech,
                    bond_symbol=selected_bond,
                    lookback_window=lookback_window,
                    start_time=str(start_date),
                    end_time=str(end_date),
                    benchmark=benchmark
                )
                os.makedirs("./reports", exist_ok=True)
                res_df.to_csv(TWIN_BOND_REPORT_CSV)
                st.success(f"攻守轮动策略回测完成！区间: {res_df.index.min().strftime('%Y-%m-%d')} ~ {res_df.index.max().strftime('%Y-%m-%d')} (共 {len(res_df)} 交易日)")
            except Exception as e:
                st.error(f"轮动策略执行失败: {e}")

    active_csv = TWIN_BOND_REPORT_CSV if os.path.exists(TWIN_BOND_REPORT_CSV) else None

# ==========================================
# 模式三：AI 机器学习 (LightGBM + Alpha158)
# ==========================================
else:
    st.sidebar.subheader("📅 时间周期")
    train_range = st.sidebar.date_input(
        "训练周期 (Train)",
        [pd.to_datetime("2017-01-01"), pd.to_datetime("2019-12-31")]
    )
    test_range = st.sidebar.date_input(
        "回测周期 (Backtest)",
        [pd.to_datetime("2020-07-01"), pd.to_datetime("2020-12-31")]
    )

    st.sidebar.subheader("🎯 组合构建规则")
    top_k = st.sidebar.slider("每日持仓股票数 (Top-K)", min_value=5, max_value=50, value=30, step=5)
    n_drop = st.sidebar.slider("每日调仓淘汰数 (N-Drop)", min_value=1, max_value=20, value=5, step=1)

    run_ai_btn = st.sidebar.button("🚀 启动 AI 模型训练与回测", type="primary", use_container_width=True)

    if run_ai_btn:
        if len(train_range) < 2 or len(test_range) < 2:
            st.error("⚠️ 请在日历中选择完整的【开始日期】与【结束日期】（需各点选两次完成区间选择）！")
        else:
            t_start = str(train_range[0])
            t_end = str(train_range[1])
            te_start = str(test_range[0])
            te_end = str(test_range[1])

            if pd.to_datetime(t_end) >= pd.to_datetime(te_start):
                st.error(f"⚠️ 时间逻辑错误: 训练集结束时间 ({t_end}) 必须严格早于回测测试集开始时间 ({te_start})，避免未来数据穿越！")
            else:
                with st.spinner(f"正在提取 Alpha158 因子并针对回测区间 [{te_start} ~ {te_end}] 执行模型训练与撮合回测..."):
                    if os.path.exists(REPORT_CSV):
                        os.remove(REPORT_CSV)
                    cmd = [
                        sys.executable,
                        "run_quant_pipeline.py",
                        "--market", market,
                        "--benchmark", benchmark,
                        "--train_start", t_start,
                        "--train_end", t_end,
                        "--test_start", te_start,
                        "--test_end", te_end,
                        "--top_k", str(top_k),
                        "--n_drop", str(n_drop),
                        "--open_cost", str(open_cost_bp / 10000),
                        "--close_cost", str(close_cost_bp / 10000),
                    ]
                    res = subprocess.run(cmd, capture_output=True, text=True)
                    if res.returncode == 0:
                        st.success(f"AI 策略回测完成！区间: {te_start} ~ {te_end}")
                    else:
                        st.error("回测执行遇到异常，请查看详情：")
                        with st.expander("查看详细错误日志"):
                            st.code(res.stderr if res.stderr else res.stdout)

    active_csv = REPORT_CSV if os.path.exists(REPORT_CSV) else None

# ==========================================
# 通用绩效结果展示渲染
# ==========================================
if active_csv and os.path.exists(active_csv):
    df = pd.read_csv(active_csv, index_col=0, parse_dates=True)
    
    start_dt_str = df.index.min().strftime('%Y-%m-%d')
    end_dt_str = df.index.max().strftime('%Y-%m-%d')
    
    st.info(f"📌 **实际呈现回测区间**: `{start_dt_str}` 至 `{end_dt_str}` (共包含 **{len(df)}** 个历史交易日)")
    if pd.to_datetime(end_dt_str) < pd.to_datetime("2021-06-15"):
        st.warning("💡 **为什么数据截止到 2021-06？** 本地微软 Qlib 离线数据集覆盖区间为 **2005-01-04 至 2021-06-11**。系统会自动在数据最后一天（2021-06-11）结束回测。\n\n👉 **如需回测 5 年以上长期数据**：请将【开始日期】往前调（例如选 `2015-01-01 至 2020-12-31`，即可拥有完整的 6 年 1400+ 个交易日数据！）。")
    
    # 计算累计净值与指标
    df["strat_cum"] = (1 + df["return"]).cumprod()
    df["bench_cum"] = (1 + df["bench"]).cumprod()
    df["excess_cum"] = df["strat_cum"] / df["bench_cum"]
    df["strat_peak"] = df["strat_cum"].cummax()
    df["drawdown"] = (df["strat_cum"] - df["strat_peak"]) / df["strat_peak"]

    total_return = df["strat_cum"].iloc[-1] - 1
    bench_return = df["bench_cum"].iloc[-1] - 1
    excess_return = df["excess_cum"].iloc[-1] - 1
    max_drawdown = df["drawdown"].min()
    
    # 严格按照【起始日到结束日】计算实际年限与年化复利收益率 (CAGR)
    start_dt = df.index.min()
    end_dt = df.index.max()
    calendar_days = (end_dt - start_dt).days
    years = max(calendar_days / 365.25, len(df) / 252.0, 0.01)
    
    # 年化复利收益率 (CAGR) = (期末净值 / 期初净值) ^ (1 / 年数) - 1
    strat_final_nav = df["strat_cum"].iloc[-1]
    bench_final_nav = df["bench_cum"].iloc[-1]
    
    cagr = (strat_final_nav ** (1.0 / years)) - 1 if strat_final_nav > 0 else -1.0
    bench_cagr = (bench_final_nav ** (1.0 / years)) - 1 if bench_final_nav > 0 else -1.0
    
    daily_vol = df["return"].std() * np.sqrt(252)
    sharpe = (cagr - 0.02) / (daily_vol if daily_vol > 0 else 1e-6)
    
    # 卡玛比率 (Calmar Ratio = 年化复利收益率 / 最大回撤)
    calmar = abs(cagr / max_drawdown) if max_drawdown != 0 else 0.0

    # 1. 核心指标卡片
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("策略累计收益率", f"{total_return * 100:.2f}%", f"{(total_return - bench_return) * 100:+.2f}% 相对基准", help="回测全周期资金累计总回报率")
    with col2:
        st.metric(
            "年化复利收益率 (CAGR)",
            f"{cagr * 100:.2f}%",
            f"{(cagr - bench_cagr) * 100:+.2f}% 较基准年化",
            help=f"从起始日 {start_dt.strftime('%Y-%m-%d')} 至结束日 {end_dt.strftime('%Y-%m-%d')} (历时 {years:.2f} 年)，考虑利滚利后的几何平均年化复利收益率"
        )
    with col3:
        st.metric("基准累计 / 年化复利", f"{bench_return * 100:.2f}%", f"年化复利 {bench_cagr * 100:.2f}%", help="基准指数(沪深300)在同期的累计收益率与年化复利收益率")
    with col4:
        st.metric("超额收益 (Alpha)", f"{excess_return * 100:.2f}%", "扣除交易费后")
    with col5:
        st.metric("最大回撤 (Max DD)", f"{max_drawdown * 100:.2f}%", help="回测期间账户净值从历史最高点跌落的最大幅度")
    with col6:
        st.metric("年化夏普比率 (Sharpe)", f"{sharpe:.2f}", f"卡玛比 {calmar:.2f}", help="夏普比率衡量每承受1单位总风险带来的超额年化收益；卡玛比=年化复利/最大回撤")

    st.markdown("---")

    # 2. 交互式可视化走势图 (分四个独立专业标签页展示，结构严密清晰)
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 绩效净值与风险分析",
        "📅 周期收益剖析 (年/季/月)",
        "🧾 券商逐笔交割与同花顺复盘",
        "📋 每日撮合流水与持仓样本"
    ])

    with tab1:
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.04,
            row_heights=[0.55, 0.25, 0.20],
            subplot_titles=["累计净值对比 (Cumulative NAV)", "动态回撤走势 (Drawdown)", "单日换手率 (Turnover)"]
        )

        # 主策略净值
        fig.add_trace(
            go.Scatter(x=df.index, y=df["strat_cum"], mode="lines", name="⭐ 轮动策略净值 (攻守兼备)", line=dict(color="#e74c3c", width=3.0)),
            row=1, col=1
        )
        
        # 单一进攻标的纯持有曲线 (Buy & Hold)
        if "asset1_ret" in df.columns:
            a1_name = df["asset1_name"].iloc[0] if "asset1_name" in df.columns else "进攻标的纯持有"
            a1_cum = (1 + df["asset1_ret"]).cumprod()
            fig.add_trace(
                go.Scatter(x=df.index, y=a1_cum, mode="lines", name=f"🚀 {a1_name}", line=dict(color="#e67e22", width=1.8, dash="dot")),
                row=1, col=1
            )
            
        # 单一防守标的纯持有曲线 (Buy & Hold)
        if "asset2_ret" in df.columns:
            a2_name = df["asset2_name"].iloc[0] if "asset2_name" in df.columns else "防守标的纯持有"
            a2_cum = (1 + df["asset2_ret"]).cumprod()
            fig.add_trace(
                go.Scatter(x=df.index, y=a2_cum, mode="lines", name=f"🛡️ {a2_name}", line=dict(color="#9b59b6", width=1.8, dash="dashdot")),
                row=1, col=1
            )

        # 业绩比较基准 (沪深300)
        fig.add_trace(
            go.Scatter(x=df.index, y=df["bench_cum"], mode="lines", name="📌 基准指数 (沪深300)", line=dict(color="#3498db", width=1.5, dash="dash")),
            row=1, col=1
        )
        # 超额收益
        fig.add_trace(
            go.Scatter(x=df.index, y=df["excess_cum"], mode="lines", name="超额净值 (Alpha)", line=dict(color="#2ecc71", width=1.5, dash="dot")),
            row=1, col=1
        )

        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["drawdown"],
                mode="lines", name="策略回撤",
                fill="tozeroy",
                line=dict(color="#c0392b", width=1),
                fillcolor="rgba(231, 76, 60, 0.25)"
            ),
            row=2, col=1
        )

        fig.add_trace(
            go.Bar(
                x=df.index, y=df["turnover"],
                name="换手率",
                marker_color="#9b59b6",
                opacity=0.7
            ),
            row=3, col=1
        )

        fig.update_layout(
            height=750,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=20, r=20, t=50, b=20)
        )
        st.plotly_chart(fig, use_container_width=True)

        # 3. 分年度收益率剖析表 (Annual Breakdown)
        st.subheader("📅 分年度收益率与超额剖析 (Annual Returns)")
        yearly_records = []
        df_copy = df.copy()
        df_copy["year"] = df_copy.index.year
        for yr, group in df_copy.groupby("year"):
            yr_strat = (1 + group["return"]).cumprod().iloc[-1] - 1
            yr_bench = (1 + group["bench"]).cumprod().iloc[-1] - 1
            yr_alpha = yr_strat - yr_bench
            yr_peak = (1 + group["return"]).cumprod().cummax()
            yr_dd = ((1 + group["return"]).cumprod() - yr_peak) / yr_peak
            yearly_records.append({
                "年份": str(yr),
                "交易日数": len(group),
                "策略年度收益率": f"{yr_strat * 100:+.2f}%",
                "基准年度收益率": f"{yr_bench * 100:+.2f}%",
                "年度超额收益 (Alpha)": f"{yr_alpha * 100:+.2f}%",
                "年内最大回撤": f"{yr_dd.min() * 100:.2f}%",
                "胜负状态": "跑赢基准 🟢" if yr_alpha > 0 else "跑输基准 🔴"
            })
        if yearly_records:
            st.dataframe(pd.DataFrame(yearly_records), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("📅 策略历史周期收益率全景剖析 (年 / 季 / 月)")
        st.caption("全景穿透分析历史区间每一自然年、每一季度、每一月份的绝对收益表现，评估不同市场环境下的收益稳定性")

        # 准备周期数据
        p_df = df.copy()
        p_df["year"] = p_df.index.year
        p_df["month"] = p_df.index.month
        p_df["quarter"] = p_df.index.quarter

        # 1. 每年收益率对比图 (柱状图 + 超额折线)
        yearly_summary = []
        for yr, group in p_df.groupby("year"):
            yr_strat = (1 + group["return"]).cumprod().iloc[-1] - 1
            yr_bench = (1 + group["bench"]).cumprod().iloc[-1] - 1
            yr_peak = (1 + group["return"]).cumprod().cummax()
            yr_dd = ((1 + group["return"]).cumprod() - yr_peak) / yr_peak
            yearly_summary.append({
                "年份": str(yr),
                "策略收益率": yr_strat,
                "基准收益率": yr_bench,
                "超额收益": yr_strat - yr_bench,
                "最大回撤": yr_dd.min()
            })
        y_summary_df = pd.DataFrame(yearly_summary)

        st.markdown("#### 1️⃣ 年度收益率对比 (Yearly Performance)")
        y_fig = go.Figure()
        y_fig.add_trace(go.Bar(
            x=y_summary_df["年份"],
            y=y_summary_df["策略收益率"] * 100,
            name="⭐ 策略收益率",
            marker_color=["#e74c3c" if v >= 0 else "#27ae60" for v in y_summary_df["策略收益率"]],
            text=[f"{v*100:+.2f}%" for v in y_summary_df["策略收益率"]],
            textposition="outside"
        ))
        y_fig.add_trace(go.Bar(
            x=y_summary_df["年份"],
            y=y_summary_df["基准收益率"] * 100,
            name="📌 沪深300基准",
            marker_color="#3498db",
            opacity=0.65,
            text=[f"{v*100:+.2f}%" for v in y_summary_df["基准收益率"]],
            textposition="outside"
        ))
        y_fig.update_layout(
            barmode="group",
            height=360,
            yaxis_title="收益率 (%)",
            margin=dict(l=20, r=20, t=30, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(y_fig, use_container_width=True)

        # 2. 季度收益率透视表 (Q1 ~ Q4)
        st.markdown("#### 2️⃣ 季度收益率矩阵 (Quarterly Returns)")
        yearly_map = {int(yr): val for yr, val in zip(y_summary_df["年份"], y_summary_df["策略收益率"])}
        
        q_pivot = p_df.groupby([p_df["year"], p_df["quarter"]])["return"].apply(
            lambda x: (1 + x).cumprod().iloc[-1] - 1
        ).unstack()
        q_pivot.columns = [f"第{c}季度 (Q{c})" for c in q_pivot.columns]
        
        # 添加全年度累计 (精确对齐年份索引)
        q_pivot["年度合计"] = q_pivot.index.map(yearly_map)
        
        # 格式化百分比并生成高亮样式
        def format_pct(val):
            if pd.isna(val): return "-"
            color = "#ff4d4f" if val > 0 else ("#52c41a" if val < 0 else "#8c9ba5")
            return f"<span style='color:{color}; font-weight:bold;'>{val*100:+.2f}%</span>"

        q_display = q_pivot.applymap(format_pct)
        st.write(q_display.to_html(escape=False), unsafe_allow_html=True)
        st.caption("注：A 股量化惯例红涨绿跌，+为红色盈利，-为绿色亏损")

        st.markdown("---")

        # 3. 月度收益率热力图矩阵 (Monthly Returns Heatmap / Table)
        st.markdown("#### 3️⃣ 月度收益率热力图与明细表 (Monthly Heatmap)")
        m_pivot = p_df.groupby([p_df["year"], p_df["month"]])["return"].apply(
            lambda x: (1 + x).cumprod().iloc[-1] - 1
        ).unstack()
        m_pivot.columns = [f"{c}月" for c in m_pivot.columns]
        m_pivot["年度合计"] = m_pivot.index.map(yearly_map)

        m_display = m_pivot.applymap(format_pct)
        st.write(m_display.to_html(escape=False), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        # 月度收益胜率与统计
        all_months = p_df.groupby([p_df["year"], p_df["month"]])["return"].apply(lambda x: (1 + x).cumprod().iloc[-1] - 1)
        win_months = (all_months > 0).sum()
        total_months = len(all_months)
        m_win_rate = (win_months / total_months * 100) if total_months > 0 else 0
        best_month = all_months.max()
        worst_month = all_months.min()

        m_c1, m_c2, m_c3, m_c4 = st.columns(4)
        with m_c1: st.metric("月度盈利胜率", f"{m_win_rate:.1f}%", f"盈利 {win_months} / 总 {total_months} 个月")
        with m_c2: st.metric("历史单月最佳收益", f"{best_month*100:+.2f}%")
        with m_c3: st.metric("历史单月最差收益", f"{worst_month*100:+.2f}%")
        with m_c4: st.metric("月度平均收益率", f"{all_months.mean()*100:+.2f}%")

    with tab3:
        # 1. 逐笔交割流水单生成与展示 (专属独立页面)
        st.subheader("🧾 策略逐笔交割流水单 (Trade Ledger)")
        st.caption("记录回测期间每一笔开仓买入、平仓卖出、成交价格、持仓天数与单笔盈亏，真实反映策略交易明细")

        from data.etf_pool import ETF_POOL
        from strategies.trade_visualizer import (
            generate_full_trade_ledger,
            load_symbol_kline,
            plot_tonghuashun_kline_with_trades,
            plot_stock_kline_with_trades,
            get_symbol_display_name
        )

        import streamlit.components.v1 as components
        from strategies.echarts_kline import build_tonghuashun_echarts_html

        @st.dialog("📊 同花顺专业行情与交割复盘系统", width="large")
        def show_tonghuashun_modal(sym, full_ledger, start_dt, end_dt):
            sym_name = get_symbol_display_name(sym)
            sym_ledger = full_ledger[full_ledger["标的代码"] == sym] if len(full_ledger) > 0 else pd.DataFrame()
            
            # 顶部行情概览
            sym_wins = sum(1 for _, r in sym_ledger.iterrows() if "盈利" in str(r.get("交割状态", "")))
            sym_closed = sum(1 for _, r in sym_ledger.iterrows() if r.get("卖出日期") != "当前仍持仓")
            win_rate = (sym_wins / sym_closed * 100) if sym_closed > 0 else 0.0
            
            c1, c2, c3, c4 = st.columns([1.5, 1, 1, 1])
            with c1:
                st.markdown(f"### 🏷️ **{sym.upper()}** · **{sym_name}**")
                st.caption(f"回测区间: `{start_dt.strftime('%Y-%m-%d')}` ~ `{end_dt.strftime('%Y-%m-%d')}`")
            with c2:
                st.metric("该标的交割次数", f"{len(sym_ledger)} 笔", f"已平仓 {sym_closed} 笔")
            with c3:
                st.metric("标的交易胜率", f"{win_rate:.1f}%", f"盈利 {sym_wins} / 亏损 {sym_closed - sym_wins}")
            with c4:
                avg_hold = sym_ledger["持仓天数"].mean() if len(sym_ledger) > 0 else 0
                st.metric("平均持仓周期", f"{avg_hold:.1f} 天")

            st.markdown("---")

            # 读取当前用户在弹窗中点选聚焦的单笔交割索引
            focus_trade_key = f"modal_focus_trade_{sym}"
            raw_focus = st.session_state.get(focus_trade_key, None)
            current_focus_idx = int(raw_focus) if raw_focus is not None else None

            # 绘制同花顺专业 K 线 (基于金融工业级 Apache ECharts，支持单笔交割深度聚焦放大)
            with st.spinner(f"正在加载 {sym} {sym_name} K 线并渲染同花顺操盘标记..."):
                kline_df = load_symbol_kline(sym, start_dt, end_dt)
                if kline_df is not None and len(kline_df) > 0:
                    echarts_html = build_tonghuashun_echarts_html(
                        kline_df, sym_ledger,
                        symbol_name=f"{sym.upper()} {sym_name}",
                        chart_height=630,
                        focus_trade_idx=current_focus_idx
                    )
                    components.html(echarts_html, height=645, scrolling=False)
                else:
                    st.warning(f"未找到 {sym} 的日K线数据，请检查本地缓存。")

            # 该标的逐笔交割清单 (支持点击任意行放大聚焦)
            if len(sym_ledger) > 0:
                t_col1, t_col2 = st.columns([3, 1])
                with t_col1:
                    st.markdown(f"#### 📜 **{sym_name}** 逐笔交割闭环记录")
                    st.caption("💡 **点击下方任意一行交割明细**，K 线图立即自动平滑放大并聚焦到该笔交割的微观买卖范围！亦可在图表右上角直接秒切！")
                with t_col2:
                    if st.button("🔄 还原为全景视野", key=f"reset_focus_{sym}", use_container_width=True):
                        st.session_state[focus_trade_key] = None
                        st.rerun()

                disp_cols = ["买入日期", "买入价格", "卖出日期", "卖出价格", "持仓天数", "单笔收益率", "交割状态"]
                sub_ledger_df = sym_ledger[disp_cols].reset_index(drop=True)
                
                table_sub = st.dataframe(
                    sub_ledger_df,
                    use_container_width=True,
                    height=200,
                    on_select="rerun",
                    selection_mode="single-row",
                    key=f"modal_ledger_table_select_{sym}"
                )

                if table_sub and hasattr(table_sub, "selection") and table_sub.selection.rows:
                    sel_sub_row = int(table_sub.selection.rows[0])
                    if st.session_state.get(focus_trade_key) != sel_sub_row:
                        st.session_state[focus_trade_key] = sel_sub_row
                        st.rerun()

        with st.spinner("正在解析回测历史并构建逐笔交割流水单..."):
            ledger_df = generate_full_trade_ledger(df)

        if len(ledger_df) > 0:
            # 统计核心交割数据
            total_trades = len(ledger_df)
            win_trades = sum(1 for _, r in ledger_df.iterrows() if r.get("交割状态") == "盈利 🟢")
            loss_trades = sum(1 for _, r in ledger_df.iterrows() if r.get("交割状态") == "亏损 🔴")
            closed_trades = win_trades + loss_trades
            win_rate = (win_trades / closed_trades * 100) if closed_trades > 0 else 0.0

            l_col1, l_col2, l_col3, l_col4 = st.columns(4)
            with l_col1:
                st.metric("总交割笔数", f"{total_trades} 笔")
            with l_col2:
                st.metric("已平仓笔数", f"{closed_trades} 笔", f"持仓中: {total_trades - closed_trades} 笔")
            with l_col3:
                st.metric("策略交割胜率", f"{win_rate:.1f}%", f"盈利 {win_trades} / 亏损 {loss_trades}")
            with l_col4:
                avg_hold = ledger_df["持仓天数"].mean()
                st.metric("平均持仓周期", f"{avg_hold:.1f} 天")

            # 标的快捷点击池与双击提示
            st.info("💡 **双击/点击交互提示**：点击下方表格中任意一行交割单，或点击上方标的按钮，即可瞬间弹出【同花顺专业 K 线买卖复盘】窗口！支持鼠标滚轮自由缩放与平移拖拽。")

            all_unique_syms = sorted(list(ledger_df["标的代码"].unique()))
            st.markdown("##### 📌 点击/双击标的弹出【同花顺】操盘 K 线与买卖标记：")
            
            p_cols = st.columns(min(len(all_unique_syms), 6))
            for i, sym in enumerate(all_unique_syms):
                col = p_cols[i % len(p_cols)]
                s_name = get_symbol_display_name(sym)
                if col.button(f"📊 {s_name} ({sym})", key=f"btn_sym_modal_{sym}", use_container_width=True):
                    st.session_state["trigger_modal_sym"] = sym

            # 交割单展示与标的筛选
            unique_syms = ["全部标的"] + all_unique_syms
            def sym_format(s):
                if s == "全部标的":
                    return "【查看全部标的交割记录】"
                return f"{s} | {get_symbol_display_name(s)}"

            sel_col, btn_modal_col, dl_col = st.columns([2.5, 1.5, 1])
            with sel_col:
                filter_sym = st.selectbox("🎯 筛选交割标的:", unique_syms, format_func=sym_format)
            with btn_modal_col:
                st.write("")
                st.write("")
                target_sym_to_open = filter_sym if filter_sym != "全部标的" else all_unique_syms[0]
                if st.button("🚀 弹出【同花顺】看盘复盘窗口", type="primary", use_container_width=True):
                    st.session_state["trigger_modal_sym"] = target_sym_to_open
            with dl_col:
                st.write("")
                st.write("")
                csv_ledger = ledger_df.to_csv(index=False).encode('utf-8')
                st.download_button("📥 导出交割单 CSV", data=csv_ledger, file_name="trade_ledger.csv", mime="text/csv")

            # 过滤展示的交割记录
            if filter_sym != "全部标的":
                display_ledger = ledger_df[ledger_df["标的代码"] == filter_sym].copy()
                active_sym = filter_sym
            else:
                display_ledger = ledger_df.copy()
                active_sym = ledger_df["标的代码"].iloc[0]

            display_cols = ["标的代码", "标的名称", "买入日期", "买入价格", "卖出日期", "卖出价格", "持仓天数", "单笔收益率", "交割状态"]

            # ====================================================
            # 逐笔交割流水明细交互表 (每行标的代码均可直接点击弹窗)
            # ====================================================
            st.markdown("##### 🧾 逐笔交割明细流水单（👉 **点击任意行的【标的代码】按钮，即刻弹出该标的同花顺 K 线与买卖标记**）：")

            # 分页逻辑 (每页 12 笔)
            page_size = 12
            total_records = len(display_ledger)
            total_pages = max(1, (total_records + page_size - 1) // page_size)

            if "ledger_page_num" not in st.session_state:
                st.session_state["ledger_page_num"] = 1

            # 分页与行数控制栏
            p_c1, p_c2, p_c3 = st.columns([2, 3, 2])
            with p_c1:
                if st.button("⬅️ 上一页", disabled=(st.session_state["ledger_page_num"] <= 1), use_container_width=True):
                    st.session_state["ledger_page_num"] -= 1
                    st.rerun()
            with p_c2:
                st.markdown(f"<div style='text-align:center; padding-top:6px; color:#8c9ba5; font-size:13px;'>第 <b>{st.session_state['ledger_page_num']}</b> / {total_pages} 页 (共 {total_records} 笔交割)</div>", unsafe_allow_html=True)
            with p_c3:
                if st.button("下一页 ➡️", disabled=(st.session_state["ledger_page_num"] >= total_pages), use_container_width=True):
                    st.session_state["ledger_page_num"] += 1
                    st.rerun()

            current_page = st.session_state["ledger_page_num"]
            start_row = (current_page - 1) * page_size
            end_row = min(start_row + page_size, total_records)
            page_df = display_ledger.iloc[start_row:end_row].copy()

            # 表头样式
            h1, h2, h3, h4, h5, h6, h7 = st.columns([1.6, 2.0, 1.8, 1.8, 0.8, 1.0, 1.0])
            with h1: st.markdown("**标的代码 (点击弹窗)**")
            with h2: st.markdown("**标的名称**")
            with h3: st.markdown("**买入明细**")
            with h4: st.markdown("**卖出明细**")
            with h5: st.markdown("**持仓**")
            with h6: st.markdown("**单笔收益**")
            with h7: st.markdown("**状态**")
            st.divider()

            # 逐行渲染交割单，第一列标的代码为原生点击按钮！
            for r_idx, r in page_df.iterrows():
                c1, c2, c3, c4, c5, c6, c7 = st.columns([1.6, 2.0, 1.8, 1.8, 0.8, 1.0, 1.0])
                sym = r["标的代码"]
                with c1:
                    # 点击当前行的标的代码，瞬间直接弹出该标的的同花顺 K 线窗口！
                    if st.button(f"📊 {sym}", key=f"btn_row_code_{r_idx}_{sym}", type="primary", use_container_width=True):
                        # 计算该交易在该标的子账单中的位置，以便弹窗直接放大聚焦它
                        sym_sub = ledger_df[ledger_df["标的代码"] == sym].reset_index(drop=True)
                        match_indices = sym_sub[(sym_sub["买入日期"] == r["买入日期"]) & (sym_sub["买入价格"] == r["买入价格"])].index
                        target_focus = int(match_indices[0]) if len(match_indices) > 0 else 0
                        st.session_state[f"modal_focus_trade_{sym}"] = target_focus
                        show_tonghuashun_modal(sym, ledger_df, df.index.min(), df.index.max())
                with c2:
                    st.write(r["标的名称"])
                with c3:
                    st.write(f"{r['买入日期']}<br><span style='color:#8c9ba5; font-size:12px;'>¥{r['买入价格']}</span>", unsafe_allow_html=True)
                with c4:
                    if r["卖出日期"] != "当前仍持仓":
                        st.write(f"{r['卖出日期']}<br><span style='color:#8c9ba5; font-size:12px;'>¥{r['卖出价格']}</span>", unsafe_allow_html=True)
                    else:
                        st.write("<span style='color:#e67e22;'>当前仍持仓 ⏳</span>", unsafe_allow_html=True)
                with c5:
                    st.write(f"{r['持仓天数']}天")
                with c6:
                    is_win = "+" in str(r["单笔收益率"])
                    color = "#ff3333" if is_win else "#00b060"
                    st.markdown(f"<span style='color:{color}; font-weight:bold;'>{r['单笔收益率']}</span>", unsafe_allow_html=True)
                with c7:
                    st.write(r["交割状态"])

            # 备用折叠式全量数据表格与导出
            with st.expander("📋 查看全量交割紧凑数据表 (可排序/筛选)"):
                st.dataframe(display_ledger[display_cols], use_container_width=True, height=220)

            # 2. 联动绘制选定标的的 K 线与买卖标记 (内嵌展示)
            st.markdown("---")
            st.subheader(f"📈 标的日K线与买卖交割点联动回放 ({active_sym} | {get_symbol_display_name(active_sym)})")
            st.caption(f"同花顺旗舰引擎：支持鼠标滚轮平滑缩放、鼠标拖拽、**[B]** 操盘买点、**[S]** 操盘卖点与虚线盈亏连接")

            sym_ledger = ledger_df[ledger_df["标的代码"] == active_sym]
            with st.spinner(f"正在加载 {active_sym} K 线走势并打点买卖标记..."):
                kline_df = load_symbol_kline(active_sym, df.index.min(), df.index.max())
                if kline_df is not None and len(kline_df) > 0:
                    echarts_html = build_tonghuashun_echarts_html(
                        kline_df, sym_ledger,
                        symbol_name=f"{active_sym.upper()} {get_symbol_display_name(active_sym)}",
                        chart_height=630
                    )
                else:
                    st.warning(f"未找到 {active_sym} 的 K 线数据，请确认本地缓存是否存在。")
        else:
            st.info("当前回测记录中暂未解析到交割记录。")

    with tab3:
        st.subheader("📋 每日回测撮合明细 (原始撮合流水表)")
        st.caption("记录每日总净值、基准走势、单日换手率与策略持仓股票池样本明细")
        st.dataframe(df, use_container_width=True)
        csv_bytes = df.to_csv().encode('utf-8')
        st.download_button(
            label="📥 导出每日撮合明细 CSV",
            data=csv_bytes,
            file_name="strategy_backtest_report.csv",
            mime="text/csv"
        )
else:
    st.info("尚无回测数据，请在左侧侧边栏选择参数并点击 **🚀 运行回测**！")

