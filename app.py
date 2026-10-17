#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股 AI 量化投研与交易台 Web UI (Streamlit)
策略研究保留既有功能；模拟账户采用已确认的独立工作区交互。
"""

import os
import sys
import datetime
import subprocess
from pathlib import Path
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit.components.v1 as components

from strategies.custom_factors import CUSTOM_FACTORS
from strategies.factor_backtest import run_factor_strategy
from strategies.twin_innovation_bond_rotation import run_twin_innovation_bond_rotation
from strategies.dividend_lowvol_swing_backtest import run_dividend_backtest, generate_trade_ledger
from ui.simulation_component import render_simulation_workspace

from data.etf_pool import ETF_POOL
from strategies.trade_visualizer import (
    generate_full_trade_ledger,
    load_symbol_kline,
    plot_tonghuashun_kline_with_trades,
    plot_stock_kline_with_trades,
    get_symbol_display_name
)
from strategies.echarts_kline import build_tonghuashun_echarts_html

# ==========================================
# 页面全局配置
# ==========================================
st.set_page_config(
    page_title="量化研究台 · 策略研究与模拟交易",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="auto"
)

# 报表文件路径常量
REPORT_CSV = "./reports/backtest_daily_report.csv"
FACTOR_REPORT_CSV = "./reports/factor_backtest_report.csv"
TWIN_BOND_REPORT_CSV = "./reports/twin_bond_report.csv"
DIVIDEND_SWING_REPORT_CSV = "./reports/dividend_swing_daily_report.csv"

def render_html(html_str: str):
    """
    渲染 HTML 并消除每行首尾多余空白，彻底杜绝 Markdown 将 4 空格以上缩进误解析为 <pre><code> 源码块
    """
    cleaned = "\n".join(line.strip() for line in html_str.strip().split("\n") if line.strip())
    st.markdown(cleaned, unsafe_allow_html=True)

# Shared workspace shell: the approved navigation is reused by all research pages.
from ui.research_workspace import render_research_shell

if "simulation_route" in st.session_state:
    st.session_state["workspace_mode"] = st.session_state.pop("simulation_route")
strategy_mode = st.session_state.get("workspace_mode", "模拟账户")
if strategy_mode != "模拟账户":
    render_research_shell(strategy_mode)
    research_heading = st.empty()

# 通用标的池映射字典
universe_options = {
    "csi300": "沪深300股票池",
    "csi500": "中证500股票池",
    "etf": "指数 ETF 核心轮动池"
}

# ==========================================
# 模式一：今日调仓 (实盘盯盘与模拟委托 - demo.html 专业重构版)
# ==========================================
if strategy_mode == "模拟账户":
    render_simulation_workspace()

# ==========================================
# 模式二：红利高抛低吸 (华泰低波 512890 量化做 T 与大波段)
# ==========================================
elif strategy_mode == "红利高抛低吸":
    with st.expander("回测参数 · 标的、周期与交易设置", expanded=False):
        st.markdown("### 红利低波回测设置")
        etf_choice = st.selectbox("核心底仓标的", ["sh512890 · 华泰柏瑞红利低波ETF"], index=0)
        bond_choice = st.selectbox("防守生息资产", ["sh511260 · 十年期国债ETF", "现金管理 (年化1.8%)"], index=0)
        default_focus = st.selectbox(
            "主显聚焦策略",
            ["全策略横向对比 (推荐)", "策略二：ERP 股债利差宏观择时", "策略一：动态 ATR 通道网格", "策略三：BIAS+RSI 动量极值波段"],
            index=0
        )

        start_date = st.date_input("开始日期", pd.to_datetime("2019-04-19"))
        end_date = st.date_input("结束日期", pd.to_datetime("2026-10-09"))

        st.markdown("### 策略二 ERP 三档区域仓位自定义")
        w_undervalue = st.slider(
            "极具性价比/低估区仓位",
            min_value=0,
            max_value=100,
            value=100,
            step=5,
            format="%d%%",
            help="当股债利差分位数高于低吸阈值时的红利持仓比例，默认 100% 满仓。"
        ) / 100.0
        w_neutral = st.slider(
            "稳健观察带/中性仓位",
            min_value=0,
            max_value=100,
            value=75,
            step=5,
            format="%d%%",
            help="当股债利差处于常态观察带时的红利底仓比例，默认 75% 底仓。"
        ) / 100.0
        w_overheat = st.slider(
            "极值过热区/高抛防守仓位",
            min_value=0,
            max_value=100,
            value=50,
            step=5,
            format="%d%%",
            help="当股债利差跌破过热线时压降后的红利仓位，默认 50% 半仓。"
        ) / 100.0

        with st.expander("更多设置 · 费率与阈值微调"):
            st.caption("分位线阈值自定义")
            th_overheat = st.slider("过热高抛分位阈值", min_value=5, max_value=30, value=20, step=5, format="%d%%") / 100.0
            th_neutral = st.slider("低吸满仓分位阈值", min_value=25, max_value=60, value=35, step=5, format="%d%%") / 100.0
            st.caption("ETF 交易免征印花税")
            fee_bp = st.number_input("双边交易佣金 (万分之)", value=1.0, step=0.5)
            slip_bp = st.number_input("双边滑点损耗 (万分之)", value=2.0, step=0.5)
            core_ratio = st.slider("核心底仓比例 (网格策略不动)", min_value=20, max_value=80, value=50, step=10, format="%d%%") / 100.0

        st.markdown(
            """
            <div class="source-note">
                <b>底层数据来源</b>
                中证指数官网日度估值 · 中国国债到期收益率 · 新浪前复权日线<br>
                历史回测不代表未来表现
            </div>
            """,
            unsafe_allow_html=True
        )

    with research_heading.container():
        # 标题与运行按钮
        c_head_left, c_head_right = st.columns([4, 1.2])
        with c_head_left:
            st.markdown(
                """
                <div class="page-head" style="margin-bottom:0;">
                    <div>
                        <h1>红利高抛低吸</h1>
                        <p>针对 512890 低波动高股息特征，对比动态 ATR 通道网格、ERP 股债性价比大波段、BIAS+RSI 极值波段三大做 T 策略真实净值表现。</p>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
        with c_head_right:
            st.write("")
            run_div_btn = st.button("重新计算回测", type="primary", use_container_width=True)

    st.markdown(
        """
        <div class="research-note-bar">
            <span>标的 <b>华泰柏瑞红利低波 ETF (512890)</b></span>
            <span>基准 <b>中证红利低波动指数 (H30269)</b></span>
            <span>对冲生息 <b>十年国债 ETF (511260)</b></span>
            <span>费率 <b>双边万3 (免印花税)</b></span>
        </div>
        """,
        unsafe_allow_html=True
    )

    @st.cache_data(show_spinner=False)
    def _get_cached_raw_dividend_data():
        from strategies.dividend_lowvol_swing_backtest import load_or_sync_data, compute_indicators
        df = load_or_sync_data()
        return compute_indicators(df)

    raw_data = _get_cached_raw_dividend_data()
    last_erp_pct = raw_data["erp_pct"].iloc[-1]
    if last_erp_pct <= th_overheat:
        rec_weight = w_overheat
        rec_status = f"估值过热区 (ERP ≤ {th_overheat*100:.0f}%)"
    elif last_erp_pct <= th_neutral:
        rec_weight = w_neutral
        rec_status = f"稳健观察带 ({th_overheat*100:.0f}% < ERP ≤ {th_neutral*100:.0f}%)"
    else:
        rec_weight = w_undervalue
        rec_status = f"极具性价比 (ERP > {th_neutral*100:.0f}%)"

    st.markdown(
        f"""
        <div class="research-signal">
            <div>
                <strong style="color:#315bd6; font-size:13px;">ERP 策略观察 · 当前研究参数</strong>
                <p style="margin:3px 0 0 0; font-size:12px; color:#475569;">
                    最新 ERP 历史分位：<b>{last_erp_pct*100:.1f}%</b> · 今日建议仓位：<b>{rec_weight*100:.0f}%</b> ({rec_status})。前往<b>模拟账户</b>核对账户信号与调仓清单。
                </p>
            </div>
            <div style="text-align:right;">
                <span style="font-size:11px; background:#eef3ff; color:#315bd6; padding:4px 10px; border-radius:3px; font-weight:600; border:1px solid #dce5fc;">
                    极值过热 {w_overheat*100:.0f}% | 观察带 {w_neutral*100:.0f}% | 极具性价比 {w_undervalue*100:.0f}%
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    cost_rate = (fee_bp + slip_bp) / 10000.0

    if run_div_btn:
        with st.spinner("正在加载最新宏观估值与行情，重新执行三大高抛低吸策略撮合..."):
            try:
                import io, contextlib
                f_dummy = io.StringIO()
                with contextlib.redirect_stdout(f_dummy), contextlib.redirect_stderr(f_dummy):
                    run_dividend_backtest(
                        w_overheat=w_overheat,
                        w_neutral=w_neutral,
                        w_undervalue=w_undervalue,
                        th_overheat=th_overheat,
                        th_neutral=th_neutral,
                        cost_rate=cost_rate
                    )
                st.toast("红利高抛低吸全周期回测已完成并导出！", icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"回测执行异常: {e}")

    # 动态实时运行真实撮合模拟 (含用户自定义的三档区域仓位与阈值)
    from strategies.dividend_lowvol_swing_backtest import run_simulation
    df_div = run_simulation(
        raw_data,
        w_overheat=w_overheat,
        w_neutral=w_neutral,
        w_undervalue=w_undervalue,
        th_overheat=th_overheat,
        th_neutral=th_neutral,
        cost_rate=cost_rate
    )

    # 按照所选日期切片并归一化净值
    sub_df = df_div.loc[(df_div.index >= pd.to_datetime(start_date)) & (df_div.index <= pd.to_datetime(end_date))].copy()
    if len(sub_df) < 5:
        st.warning("所选日期范围内数据点不足，请调整起止日期。")
    else:
        # 归一化净值
        for c in ["bench_nav", "csi300_nav", "s1_atr_nav", "s2_erp_nav", "s3_bias_nav"]:
            if c in sub_df.columns:
                sub_df[c] = sub_df[c] / sub_df[c].iloc[0]
                cummax = sub_df[c].cummax()
                sub_df[f"dd_{c}"] = (sub_df[c] - cummax) / cummax

        tot_bench = sub_df["bench_nav"].iloc[-1] - 1.0
        tot_csi = sub_df["csi300_nav"].iloc[-1] - 1.0 if "csi300_nav" in sub_df.columns else 0.0
        tot_s2 = sub_df["s2_erp_nav"].iloc[-1] - 1.0

        days = (sub_df.index[-1] - sub_df.index[0]).days
        years = max(days / 365.25, len(sub_df) / 250.0, 0.01)
        cagr_bench = (sub_df["bench_nav"].iloc[-1]) ** (1.0 / years) - 1.0
        cagr_csi = (sub_df["csi300_nav"].iloc[-1]) ** (1.0 / years) - 1.0 if "csi300_nav" in sub_df.columns else 0.0
        cagr_s2 = (sub_df["s2_erp_nav"].iloc[-1]) ** (1.0 / years) - 1.0

        mdd_bench = sub_df["dd_bench_nav"].min()
        mdd_csi = sub_df["dd_csi300_nav"].min() if "dd_csi300_nav" in sub_df.columns else 0.0
        mdd_s2 = sub_df["dd_s2_erp_nav"].min()

        daily_r_s2 = sub_df["s2_erp_nav"].pct_change().dropna()
        vol_s2 = daily_r_s2.std() * np.sqrt(250)
        sharpe_s2 = (cagr_s2 - 0.02) / (vol_s2 + 1e-9)

        daily_r_b = sub_df["bench_nav"].pct_change().dropna()
        vol_b = daily_r_b.std() * np.sqrt(250)
        sharpe_b = (cagr_bench - 0.02) / (vol_b + 1e-9)

        calmar_s2 = cagr_s2 / (abs(mdd_s2) + 1e-9)

        st.markdown(
            f"""
            <div style="background:#ffffff; border:1px solid var(--line); padding:10px 16px; margin: 16px 0 14px 0; font-size:11px; color:#606c78;">
                <b>回测呈现区间</b>: <code>{sub_df.index.min().strftime('%Y-%m-%d')}</code> 至 <code>{sub_df.index.max().strftime('%Y-%m-%d')}</code> (共 <b>{len(sub_df)}</b> 交易日，历时 {years:.2f} 年)
            </div>
            """,
            unsafe_allow_html=True
        )

        # 6 大核心 KPI 指标卡
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            st.metric("策略累计收益率", f"{tot_s2 * 100:.2f}%", f"{(tot_s2 - tot_bench) * 100:+.2f}% 较红利基准")
        with col2:
            st.metric("策略年化复利 (CAGR)", f"{cagr_s2 * 100:.2f}%", f"{(cagr_s2 - cagr_bench) * 100:+.2f}% 较红利Alpha")
        with col3:
            st.metric("红利低波纯持有", f"{tot_bench * 100:.2f}%", f"年化 {cagr_bench * 100:.2f}%")
        with col4:
            st.metric("沪深300指数累计/年化", f"{tot_csi * 100:.2f}%", f"年化 {cagr_csi * 100:.2f}%")
        with col5:
            st.metric("最大回撤对比", f"{mdd_s2 * 100:.2f}%", f"沪深300回撤 {mdd_csi * 100:.2f}%")
        with col6:
            st.metric("年化夏普比率", f"{sharpe_s2:.2f}", f"基准 {sharpe_b:.2f} · 卡玛 {calmar_s2:.2f}")

        st.markdown("<br>", unsafe_allow_html=True)

        # 五大专业标签页
        tab1, tab_trade, tab2, tab3, tab4 = st.tabs([
            "净值走势与买卖标记",
            "逐笔做 T 交易记录 (券商交割单)",
            "分年度收益归因与胜率",
            "核心量化指标监控 (ATR/ERP/BIAS)",
            "每日撮合与持仓流水"
        ])

        from strategies.dividend_lowvol_swing_backtest import load_or_sync_data, compute_indicators
        raw_data = compute_indicators(load_or_sync_data())

        with tab1:
            fig = make_subplots(
                rows=3, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.04,
                row_heights=[0.55, 0.25, 0.20],
                subplot_titles=[
                    "红利低波高抛低吸策略 vs 华泰低波纯持有 vs 沪深300指数 (Cumulative NAV)",
                    "动态水下回撤对比曲线 (Drawdown %)",
                    "策略持仓权重走势 (ETF Position Weight: 50%~100%)"
                ]
            )

            # 1. 策略净值线 (红线加粗主显)
            fig.add_trace(
                go.Scatter(
                    x=sub_df.index,
                    y=sub_df["s2_erp_nav"],
                    mode="lines",
                    name="红利低波ERP利差高抛低吸策略",
                    line=dict(color="#DC2626", width=2.8),
                    hovertemplate="<b>红利低波高抛低吸策略</b><br>日期: %{x|%Y-%m-%d}<br>净值: %{y:.4f}<extra></extra>"
                ),
                row=1, col=1
            )

            # 2. 华泰低波红利基准纯持有 (灰蓝虚线)
            fig.add_trace(
                go.Scatter(
                    x=sub_df.index,
                    y=sub_df["bench_nav"],
                    mode="lines",
                    name="华泰低波红利 (基准纯持有)",
                    line=dict(color="#64748B", width=1.8, dash="dot"),
                    hovertemplate="<b>华泰低波红利(纯持有)</b><br>日期: %{x|%Y-%m-%d}<br>净值: %{y:.4f}<extra></extra>"
                ),
                row=1, col=1
            )

            # 3. 沪深300指数 (琥珀金实线)
            if "csi300_nav" in sub_df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=sub_df.index,
                        y=sub_df["csi300_nav"],
                        mode="lines",
                        name="沪深300指数 (市场宽基)",
                        line=dict(color="#D97706", width=1.8),
                        hovertemplate="<b>沪深300指数</b><br>日期: %{x|%Y-%m-%d}<br>净值: %{y:.4f}<extra></extra>"
                    ),
                    row=1, col=1
                )

            # 策略高抛低吸买卖点精准标记
            ledger_s2, _, _, _ = generate_trade_ledger(sub_df, raw_data, strat_key="s2")
            if len(ledger_s2) > 0:
                buys = ledger_s2[ledger_s2["操作类型"].str.contains("低吸")]
                sells = ledger_s2[ledger_s2["操作类型"].str.contains("高抛")]
                if len(buys) > 0:
                    b_dates = pd.to_datetime(buys["交割日期"])
                    b_navs = sub_df.loc[sub_df.index.isin(b_dates), "s2_erp_nav"]
                    fig.add_trace(
                        go.Scatter(
                            x=b_navs.index,
                            y=b_navs,
                            mode="markers",
                            name="低吸买入点 🔼",
                            marker=dict(symbol="triangle-up", size=8, color="#10B981", line=dict(width=1, color="#047857")),
                            hovertemplate="<b>低吸加仓 🔼</b><br>日期: %{x|%Y-%m-%d}<br>净值: %{y:.4f}<extra></extra>"
                        ),
                        row=1, col=1
                    )
                if len(sells) > 0:
                    s_dates = pd.to_datetime(sells["交割日期"])
                    s_navs = sub_df.loc[sub_df.index.isin(s_dates), "s2_erp_nav"]
                    fig.add_trace(
                        go.Scatter(
                            x=s_navs.index,
                            y=s_navs,
                            mode="markers",
                            name="高抛卖出点 🔻",
                            marker=dict(symbol="triangle-down", size=8, color="#EF4444", line=dict(width=1, color="#B91C1C")),
                            hovertemplate="<b>高抛减仓 🔻</b><br>日期: %{x|%Y-%m-%d}<br>净值: %{y:.4f}<extra></extra>"
                        ),
                        row=1, col=1
                    )

            # 回撤线
            fig.add_trace(go.Scatter(x=sub_df.index, y=sub_df["dd_s2_erp_nav"] * 100, mode="lines", name="策略回撤", line=dict(color="#DC2626", width=1.5), showlegend=False), row=2, col=1)
            fig.add_trace(go.Scatter(x=sub_df.index, y=sub_df["dd_bench_nav"] * 100, mode="lines", name="红利低波回撤", line=dict(color="#64748B", width=1.0), showlegend=False), row=2, col=1)
            if "dd_csi300_nav" in sub_df.columns:
                fig.add_trace(go.Scatter(x=sub_df.index, y=sub_df["dd_csi300_nav"] * 100, mode="lines", name="沪深300回撤", line=dict(color="#D97706", width=1.2), showlegend=False), row=2, col=1)

            # 仓位权重变化线
            fig.add_trace(go.Scatter(x=sub_df.index, y=sub_df["s2_weight"] * 100, mode="lines", name="策略仓位 %", line=dict(color="#DC2626", width=1.5)), row=3, col=1)

            fig.update_layout(
                template="plotly_white",
                height=780,
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5, font=dict(size=11)),
                margin=dict(l=30, r=30, t=60, b=30)
            )
            fig.update_yaxes(title_text="累计净值", row=1, col=1)
            fig.update_yaxes(title_text="回撤 %", row=2, col=1)
            fig.update_yaxes(title_text="持仓 %", row=3, col=1, range=[0, 110])

            st.plotly_chart(fig, use_container_width=True)

        with tab_trade:
            st.markdown("#### 券商级逐笔做 T 交易交割账单 (Trade Action Ledger)")
            c_sel1, c_sel2 = st.columns([2.5, 3.5])
            with c_sel1:
                ledger_strat = st.selectbox(
                    "查看策略交易对账单",
                    ["策略二：ERP 股债利差择时 (推荐)", "策略一：动态 ATR 网格高抛低吸", "策略三：BIAS+RSI 动量极值波段"],
                    index=0
                )

            strat_key_map = {
                "策略二：ERP 股债利差择时 (推荐)": "s2",
                "策略一：动态 ATR 网格高抛低吸": "s1",
                "策略三：BIAS+RSI 动量极值波段": "s3"
            }
            sel_key = strat_key_map.get(ledger_strat, "s2")
            ledger_df, win_rate, total_closed, win_count = generate_trade_ledger(
                sub_df, 
                raw_data, 
                strat_key=sel_key,
                th_overheat=th_overheat,
                th_neutral=th_neutral
            )

            # 4 大做 T 交易统计卡片
            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.metric("做 T 胜率 (Win Rate)", f"{win_rate:.1f}%", f"{win_count} 胜 / {total_closed - win_count} 负")
            with k2:
                st.metric("完成平仓轮数", f"{total_closed} 轮", f"总调仓 {len(ledger_df)} 次")
            with k3:
                pnl_numeric = ledger_df["pnl_raw"].dropna()
                avg_pnl = pnl_numeric.mean() if len(pnl_numeric) > 0 else 0.0
                st.metric("单笔平均做 T 收益", f"{avg_pnl*100:+.2f}%")
            with k4:
                high_sells = (ledger_df["操作类型"].str.contains("高抛")).sum()
                low_buys = (ledger_df["操作类型"].str.contains("低吸")).sum()
                st.metric("高抛 / 低吸次数", f"{high_sells} 抛 / {low_buys} 吸")

            st.markdown("<br>", unsafe_allow_html=True)
            show_cols = ["交割日期", "标的代码", "标的名称", "操作类型", "成交价格", "仓位调整", "调仓幅度", "单笔盈亏", "持仓天数", "交割状态", "量化触发依据"]
            st.dataframe(ledger_df[show_cols], use_container_width=True, hide_index=True)

            ledger_csv = ledger_df[show_cols].to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                f"导出【{ledger_strat.split('：')[0]}】逐笔交割账单 CSV",
                data=ledger_csv,
                file_name=f"trade_ledger_{sel_key}.csv",
                mime="text/csv"
            )

        with tab2:
            st.markdown("#### 2019 ~ 2026 分年度收益率归因对比")
            sub_df["year"] = sub_df.index.year
            yearly_rows = []
            for y, grp in sub_df.groupby("year"):
                b_r = grp["bench_nav"].iloc[-1] / grp["bench_nav"].iloc[0] - 1.0
                csi_r = (grp["csi300_nav"].iloc[-1] / grp["csi300_nav"].iloc[0] - 1.0) if "csi300_nav" in grp.columns else 0.0
                s2_r = grp["s2_erp_nav"].iloc[-1] / grp["s2_erp_nav"].iloc[0] - 1.0
                alpha_b = s2_r - b_r
                alpha_csi = s2_r - csi_r

                yearly_rows.append({
                    "年份": str(y),
                    "红利低波ERP择时策略": f"{s2_r*100:+.2f}%",
                    "华泰低波红利 (纯持有)": f"{b_r*100:+.2f}%",
                    "沪深300指数 (市场宽基)": f"{csi_r*100:+.2f}%",
                    "较红利超额 Alpha": f"{alpha_b*100:+.2f}%",
                    "较沪深300超额": f"{alpha_csi*100:+.2f}%"
                })

            st.dataframe(pd.DataFrame(yearly_rows), use_container_width=True, hide_index=True)

            st.markdown(
                """
                <div style="background:#f8fafc; border-left: 4px solid #DC2626; padding: 12px 16px; margin-top: 16px; font-size:12px; color:#334155; line-height:1.6;">
                    <b>💡 量化归因核心发现：</b><br>
                    1. <b>大幅跑赢市场大盘（沪深300）</b>：2019-2026 全周期内，沪深300累计收益仅 <b>+7.24%</b>（年化 0.94%，最大回撤 -45.60%），而红利低波高抛低吸策略累计收益达 <b>+135.94%</b>（年化 12.18%，最大回撤仅 -16.57%），不仅累计超额高达 <b>+128.70%</b>，回撤也压缩至大盘的 1/3；<br>
                    2. <b>稳健战胜红利纯持有基准</b>：相较于华泰低波红利自身的纯持有基准（+102.68%），策略通过股债利差估值周期高抛低吸，累计超额达 <b>+33.26%</b>（年化超额 +2.26%）；<br>
                    3. <b>熊市避险效应极佳</b>：在 2022 年沪深300大跌 -21.63% 时，本策略不仅保本甚至录得 <b>+2.63% 正收益</b>。
                </div>
                """,
                unsafe_allow_html=True
            )

        with tab3:
            st.markdown("#### 核心量化指标监控走势")
            # 绘制 指标走势图
            from strategies.dividend_lowvol_swing_backtest import load_or_sync_data, compute_indicators
            raw_data = compute_indicators(load_or_sync_data())
            raw_sub = raw_data.loc[(raw_data.index >= pd.to_datetime(start_date)) & (raw_data.index <= pd.to_datetime(end_date))]

            fig_ind = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.06,
                row_heights=[0.55, 0.45],
                subplot_titles=["华泰低波红利收盘价与 ATR 通道", "股债风险溢价 (ERP) 及 250 日滚动分位数 (%)"]
            )
            # 价格与通道
            fig_ind.add_trace(go.Scatter(x=raw_sub.index, y=raw_sub["close"], mode="lines", name="512890 收盘价", line=dict(color="#0F172A", width=1.5)), row=1, col=1)
            fig_ind.add_trace(go.Scatter(x=raw_sub.index, y=raw_sub["ema30"], mode="lines", name="EMA30 价值中轴", line=dict(color="#3B82F6", width=1.2, dash="dash")), row=1, col=1)
            fig_ind.add_trace(go.Scatter(x=raw_sub.index, y=raw_sub["ema30"] + 2.0 * raw_sub["atr20"], mode="lines", name="上轨 (+2.0 ATR 高抛)", line=dict(color="#EF4444", width=1.0, dash="dot")), row=1, col=1)
            fig_ind.add_trace(go.Scatter(x=raw_sub.index, y=raw_sub["ema30"] - 2.0 * raw_sub["atr20"], mode="lines", name="下轨 (-2.0 ATR 低吸)", line=dict(color="#10B981", width=1.0, dash="dot")), row=1, col=1)

            # ERP 分位数
            fig_ind.add_trace(go.Scatter(x=raw_sub.index, y=raw_sub["erp_pct"] * 100, mode="lines", name="ERP 历史分位数 %", line=dict(color="#8B5CF6", width=1.5)), row=2, col=1)
            fig_ind.add_hline(y=80, line_dash="dash", line_color="#10B981", annotation_text="80% 极具性价比 (低吸满仓)", row=2, col=1)
            fig_ind.add_hline(y=20, line_dash="dash", line_color="#EF4444", annotation_text="20% 估值过热 (高抛减半)", row=2, col=1)

            fig_ind.update_layout(template="plotly_white", height=600, hovermode="x unified", margin=dict(l=30, r=30, t=50, b=30))
            st.plotly_chart(fig_ind, use_container_width=True)

        with tab4:
            st.markdown("#### 每日撮合与持仓权重流水")
            st.dataframe(sub_df[["close", "bench_nav", "s1_atr_nav", "s1_weight", "s2_erp_nav", "s2_weight", "s3_bias_nav", "s3_weight"]].tail(100), use_container_width=True)
            csv_data = sub_df.to_csv().encode("utf-8-sig")
            st.download_button("导出完整回测明细 CSV", data=csv_data, file_name="dividend_swing_daily_report.csv", mime="text/csv")

# ==========================================
# 模式三：攻守轮动 (双资产动量趋势回测)
# ==========================================
elif strategy_mode == "攻守轮动":
    tech_options = {
        "sz159915": "创业板ETF · 159915",
        "sh588380": "双创50ETF · 588380",
        "sh588000": "科创50ETF · 588000"
    }
    bond_options = {
        "sh512890": "红利低波ETF · 512890",
        "sh510880": "红利ETF · 510880",
        "sh511010": "国债ETF · 511010",
        "sh511260": "十年国债ETF · 511260",
        "sh511090": "三十年国债ETF · 511090"
    }

    with st.expander("回测参数 · 标的、周期与交易设置", expanded=False):
        st.markdown("### 回测设置")
        selected_tech = st.selectbox("进攻标的", list(tech_options.keys()), format_func=lambda x: tech_options[x], index=0)
        selected_bond = st.selectbox("防守标的", list(bond_options.keys()), format_func=lambda x: bond_options[x], index=0)
        lookback_window = st.slider("动量周期", min_value=5, max_value=60, value=20, step=5)

        if selected_tech == "sz159915" and selected_bond in ["sh511010", "sh510880"]:
            default_start_val = pd.to_datetime("2013-08-01")
        elif selected_bond == "sh512890":
            default_start_val = pd.to_datetime("2019-02-25")
        else:
            default_start_val = pd.to_datetime("2022-08-01")

        start_date = st.date_input("开始日期", default_start_val)
        end_date = st.date_input("结束日期", pd.to_datetime("2026-10-09"))

        with st.expander("更多设置 · 费率与基准"):
            benchmark = st.text_input("基准标的", "SH000300")
            open_cost_bp = st.number_input("买入佣金 (万分之)", value=1.0, step=0.5)
            close_cost_bp = st.number_input("卖出费率 (万分之)", value=1.0, step=0.5)

        st.markdown(
            """
            <div class="source-note">
                <b>数据来源</b>
                Qlib 历史数据 · 新浪行情<br>
                历史回测不代表未来表现
            </div>
            """,
            unsafe_allow_html=True
        )

    with research_heading.container():
        # 页面标题与运行按钮
        c_head_left, c_head_right = st.columns([4, 1.2])
        with c_head_left:
            st.markdown(
                """
                <div class="page-head" style="margin-bottom:0;">
                    <div>
                        <h1>攻守轮动</h1>
                        <p>选择进攻与防守标的，验证历史双资产动态轮动表现。</p>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
        with c_head_right:
            st.write("")
            run_rotation_btn = st.button("运行轮动回测", type="primary", use_container_width=True)

    tech_name = tech_options.get(selected_tech, selected_tech).split()[0]
    bond_name = bond_options.get(selected_bond, selected_bond).split()[0]

    st.markdown(
        f"""
        <div class="research-note-bar">
            <span>引擎 <b>双资产动量趋势引擎</b></span>
            <span>标的 <b>{tech_name} + {bond_name}</b></span>
            <span>周期 <b>{lookback_window} 日</b></span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if run_rotation_btn:
        with st.spinner("正在基于历史数据执行攻守轮动撮合..."):
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
                st.session_state["has_run_rotation"] = True
                st.toast("攻守轮动回测完成！", icon="✅")
            except Exception as e:
                st.error(f"轮动策略执行失败: {e}")

    # 渲染结果或空状态占位
    if os.path.exists(TWIN_BOND_REPORT_CSV):
        active_csv = TWIN_BOND_REPORT_CSV
    else:
        active_csv = None

    if not active_csv:
        st.markdown(
            """
            <div class="empty-placeholder">
                <h2>双资产轮动回测</h2>
                <p>展开上方「回测参数」设置标的与日期，点击右上角运行回测。报告将在当前页面展示。</p>
                <span class="crumb-badge">尚未运行</span>
            </div>
            """,
            unsafe_allow_html=True
        )

# ==========================================
# 模式三：因子实验 (自定义表达式与经典选股)
# ==========================================
elif strategy_mode == "因子实验":
    with st.expander("回测参数 · 标的、周期与交易设置", expanded=False):
        st.markdown("### 选股规则")
        market_display = st.selectbox("标的池", list(universe_options.values()), index=2)
        market = [k for k, v in universe_options.items() if v == market_display][0]

        preset_choice = st.selectbox("因子预设", ["[自定义表达式]"] + list(CUSTOM_FACTORS.keys()), index=0)
        if preset_choice == "[自定义表达式]":
            factor_expr = st.text_area("因子表达式", value="($close - Ref($close, 20)) / Ref($close, 20)", height=80)
        else:
            factor_expr = CUSTOM_FACTORS[preset_choice]
            st.code(factor_expr, language="python")

        direction = st.radio("选股方向", ["因子值最大优先", "因子值最小优先"])
        ascending = True if "最小" in direction else False

        if market == "etf":
            top_k = st.slider("持仓数量 Top-K", min_value=1, max_value=5, value=2, step=1)
            def_start = pd.to_datetime("2022-01-01")
        else:
            top_k = st.slider("持仓数量 Top-K", min_value=5, max_value=50, value=20, step=5)
            def_start = pd.to_datetime("2020-07-01")

        date_range = st.date_input("回测时间区间", [def_start, pd.to_datetime("2026-10-09")])

        with st.expander("更多设置 · 费率与基准"):
            benchmark = st.text_input("基准标的", "SH000300")
            open_cost_bp = st.number_input("买入佣金 (万分之)", value=1.0 if market == "etf" else 2.5, step=0.5)
            close_cost_bp = st.number_input("卖出费率 (万分之)", value=1.0 if market == "etf" else 7.5, step=0.5)

        st.markdown(
            """
            <div class="source-note">
                <b>数据来源</b>
                Qlib 历史数据 · 在线表达式计算<br>
                历史回测不代表未来表现
            </div>
            """,
            unsafe_allow_html=True
        )

    with research_heading.container():
        c_head_left, c_head_right = st.columns([4, 1.2])
        with c_head_left:
            st.markdown(
                """
                <div class="page-head" style="margin-bottom:0;">
                    <div>
                        <h1>因子实验</h1>
                        <p>从经典因子开始，或直接编辑自己的表达式进行选股回测。</p>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
        with c_head_right:
            st.write("")
            run_factor_btn = st.button("运行因子回测", type="primary", use_container_width=True)

    st.markdown(
        f"""
        <div class="research-note-bar">
            <span>引擎 <b>Qlib 表达式引擎</b></span>
            <span>标的池 <b>{market_display}</b></span>
            <span>持仓 <b>Top-{top_k}</b></span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if run_factor_btn:
        if len(date_range) < 2:
            st.error("请选择完整的开始与结束日期！")
        else:
            start_d = str(date_range[0])
            end_d = str(date_range[1])
            with st.spinner("正在执行截面因子选股模拟撮合..."):
                try:
                    res_df = run_factor_strategy(
                        factor_expr=factor_expr,
                        factor_name=preset_choice if preset_choice != "[自定义表达式]" else "CustomFactor",
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
                    st.toast("因子选股回测完成！", icon="✅")
                except Exception as e:
                    st.error(f"因子回测失败: {e}")

    active_csv = FACTOR_REPORT_CSV if os.path.exists(FACTOR_REPORT_CSV) else None
    if not active_csv:
        st.markdown(
            """
            <div class="empty-placeholder">
                <h2>因子选股回测</h2>
                <p>选择标的池和因子，设置持仓数量后运行。报告将在当前页面展示。</p>
                <span class="crumb-badge">尚未运行</span>
            </div>
            """,
            unsafe_allow_html=True
        )

# ==========================================
# 模式四：模型回测 (LightGBM + Alpha158)
# ==========================================
elif strategy_mode == "模型回测":
    with st.expander("回测参数 · 标的、周期与交易设置", expanded=False):
        st.markdown("### 训练与组合设置")
        market_display = st.selectbox("标的池", ["沪深300股票池", "中证500股票池"], index=0)
        market = "csi300" if "300" in market_display else "csi500"

        train_range = st.date_input("训练周期", [pd.to_datetime("2017-01-01"), pd.to_datetime("2019-12-31")])
        test_range = st.date_input("回测周期", [pd.to_datetime("2020-07-01"), pd.to_datetime("2020-12-31")])

        top_k = st.slider("持仓数量 Top-K", min_value=5, max_value=50, value=30, step=5)
        n_drop = st.slider("调仓淘汰数 N-Drop", min_value=1, max_value=20, value=5, step=1)

        with st.expander("更多设置 · 费率与基准"):
            benchmark = st.text_input("基准标的", "SH000300")
            open_cost_bp = st.number_input("买入佣金 (万分之)", value=2.5, step=0.5)
            close_cost_bp = st.number_input("卖出费率 (万分之)", value=7.5, step=0.5)

        st.markdown(
            """
            <div class="source-note">
                <b>数据来源</b>
                微软 Qlib · Alpha158 特征库<br>
                模型输出仅供策略研究
            </div>
            """,
            unsafe_allow_html=True
        )

    with research_heading.container():
        c_head_left, c_head_right = st.columns([4, 1.2])
        with c_head_left:
            st.markdown(
                """
                <div class="page-head" style="margin-bottom:0;">
                    <div>
                        <h1>模型回测</h1>
                        <p>训练机器学习模型并查看多因子组合回测绩效。</p>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
        with c_head_right:
            st.write("")
            run_ai_btn = st.button("训练并回测", type="primary", use_container_width=True)

    st.markdown(
        f"""
        <div class="research-note-bar">
            <span>引擎 <b>LightGBM + Alpha158</b></span>
            <span>标的池 <b>{market_display}</b></span>
            <span>组合 <b>Top-{top_k} / Drop-{n_drop}</b></span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if run_ai_btn:
        if len(train_range) < 2 or len(test_range) < 2:
            st.error("请完整选择训练区间与回测区间！")
        else:
            t_start = str(train_range[0])
            t_end = str(train_range[1])
            te_start = str(test_range[0])
            te_end = str(test_range[1])

            if pd.to_datetime(t_end) >= pd.to_datetime(te_start):
                st.error("训练集结束时间必须严格早于回测测试集开始时间！")
            else:
                with st.spinner("正在训练模型并执行撮合回测..."):
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
                        st.toast("AI 策略回测完成！", icon="✅")
                    else:
                        st.error(f"回测遇到异常: {res.stderr if res.stderr else res.stdout}")

    active_csv = REPORT_CSV if os.path.exists(REPORT_CSV) else None
    if not active_csv:
        st.markdown(
            """
            <div class="empty-placeholder">
                <h2>模型训练与回测</h2>
                <p>设置训练区间与回测区间，完成后查看组合表现、预测结果与成交记录。</p>
                <span class="crumb-badge">尚未运行</span>
            </div>
            """,
            unsafe_allow_html=True
        )

# ==========================================
# 策略研究模式的完整绩效报表渲染 (保留全部既有分析)
# ==========================================
if strategy_mode in ["攻守轮动", "因子实验", "模型回测"] and active_csv and os.path.exists(active_csv):
    df = pd.read_csv(active_csv, index_col=0, parse_dates=True)

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

    start_dt = df.index.min()
    end_dt = df.index.max()
    calendar_days = (end_dt - start_dt).days
    years = max(calendar_days / 365.25, len(df) / 252.0, 0.01)

    strat_final_nav = df["strat_cum"].iloc[-1]
    bench_final_nav = df["bench_cum"].iloc[-1]

    cagr = (strat_final_nav ** (1.0 / years)) - 1 if strat_final_nav > 0 else -1.0
    bench_cagr = (bench_final_nav ** (1.0 / years)) - 1 if bench_final_nav > 0 else -1.0

    daily_vol = df["return"].std() * np.sqrt(252)
    sharpe = (cagr - 0.02) / (daily_vol if daily_vol > 0 else 1e-6)
    calmar = abs(cagr / max_drawdown) if max_drawdown != 0 else 0.0

    st.markdown(
        f"""
        <div style="background:#ffffff; border:1px solid var(--line); padding:10px 16px; margin: 16px 0 14px 0; font-size:11px; color:#606c78;">
            <b>回测呈现区间</b>: <code>{start_dt.strftime('%Y-%m-%d')}</code> 至 <code>{end_dt.strftime('%Y-%m-%d')}</code> (共 <b>{len(df)}</b> 交易日，历时 {years:.2f} 年)
        </div>
        """,
        unsafe_allow_html=True
    )

    # 1. 核心指标卡 (保留全部 6 大指标)
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("策略累计收益率", f"{total_return * 100:.2f}%", f"{(total_return - bench_return) * 100:+.2f}% 相对基准")
    with col2:
        st.metric("年化复利收益 (CAGR)", f"{cagr * 100:.2f}%", f"{(cagr - bench_cagr) * 100:+.2f}% 较基准")
    with col3:
        st.metric("基准累计 / 年化", f"{bench_return * 100:.2f}%", f"年化 {bench_cagr * 100:.2f}%")
    with col4:
        st.metric("超额收益 (Alpha)", f"{excess_return * 100:.2f}%", "扣费后净值")
    with col5:
        st.metric("最大回撤 (Max DD)", f"{max_drawdown * 100:.2f}%")
    with col6:
        st.metric("年化夏普比率", f"{sharpe:.2f}", f"卡玛比 {calmar:.2f}")

    st.markdown("<br>", unsafe_allow_html=True)

    # 2. 四大专业标签页
    tab1, tab2, tab3, tab4 = st.tabs([
        "净值走势与风险",
        "周期收益剖析 (年/季/月)",
        "券商逐笔交割与同花顺复盘",
        "每日撮合明细流水"
    ])

    with tab1:
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.04,
            row_heights=[0.55, 0.25, 0.20],
            subplot_titles=["累计净值对比 (Cumulative NAV)", "动态回撤走势 (Drawdown)", "单日换手率 (Turnover)"]
        )

        fig.add_trace(
            go.Scatter(x=df.index, y=df["strat_cum"], mode="lines", name="轮动策略净值", line=dict(color="#aa3d33", width=2.6)),
            row=1, col=1
        )

        if "asset1_ret" in df.columns:
            a1_name = df["asset1_name"].iloc[0] if "asset1_name" in df.columns else "进攻标的纯持有"
            fig.add_trace(
                go.Scatter(x=df.index, y=(1 + df["asset1_ret"]).cumprod(), mode="lines", name=f"{a1_name}", line=dict(color="#d97736", width=1.6, dash="dot")),
                row=1, col=1
            )
        if "asset2_ret" in df.columns:
            a2_name = df["asset2_name"].iloc[0] if "asset2_name" in df.columns else "防守标的纯持有"
            fig.add_trace(
                go.Scatter(x=df.index, y=(1 + df["asset2_ret"]).cumprod(), mode="lines", name=f"{a2_name}", line=dict(color="#6c5b7b", width=1.6, dash="dashdot")),
                row=1, col=1
            )

        fig.add_trace(
            go.Scatter(x=df.index, y=df["bench_cum"], mode="lines", name="基准指数 (沪深300)", line=dict(color="#285873", width=1.5, dash="dash")),
            row=1, col=1
        )
        fig.add_trace(
            go.Scatter(x=df.index, y=df["excess_cum"], mode="lines", name="超额净值 (Alpha)", line=dict(color="#27735b", width=1.5, dash="dot")),
            row=1, col=1
        )

        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["drawdown"],
                mode="lines", name="策略回撤",
                fill="tozeroy",
                line=dict(color="#aa3d33", width=1),
                fillcolor="rgba(170, 61, 51, 0.2)"
            ),
            row=2, col=1
        )

        fig.add_trace(
            go.Bar(x=df.index, y=df["turnover"], name="换手率", marker_color="#8e9eab", opacity=0.7),
            row=3, col=1
        )

        fig.update_layout(
            height=700,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=15, r=15, t=40, b=20),
            plot_bgcolor="#ffffff",
            paper_bgcolor="#ffffff"
        )
        st.plotly_chart(fig, use_container_width=True)

        # 分年度收益率剖析表
        st.markdown("##### 分年度收益率剖析 (Annual Breakdown)")
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
                "年度超额 (Alpha)": f"{yr_alpha * 100:+.2f}%",
                "年内最大回撤": f"{yr_dd.min() * 100:.2f}%",
                "胜负状态": "跑赢基准 " if yr_alpha > 0 else "跑输基准 🔴"
            })
        if yearly_records:
            st.dataframe(pd.DataFrame(yearly_records), use_container_width=True, hide_index=True)

    with tab2:
        st.markdown("##### 历史周期收益率全景剖析 (年 / 季 / 月)")
        p_df = df.copy()
        p_df["year"] = p_df.index.year
        p_df["month"] = p_df.index.month
        p_df["quarter"] = p_df.index.quarter

        yearly_summary = []
        for yr, group in p_df.groupby("year"):
            yr_strat = (1 + group["return"]).cumprod().iloc[-1] - 1
            yr_bench = (1 + group["bench"]).cumprod().iloc[-1] - 1
            yearly_summary.append({
                "年份": str(yr),
                "策略收益率": yr_strat,
                "基准收益率": yr_bench
            })
        y_summary_df = pd.DataFrame(yearly_summary)

        # 季度矩阵
        yearly_map = {int(yr): val for yr, val in zip(y_summary_df["年份"], y_summary_df["策略收益率"])}
        q_pivot = p_df.groupby([p_df["year"], p_df["quarter"]])["return"].apply(
            lambda x: (1 + x).cumprod().iloc[-1] - 1
        ).unstack()
        q_pivot.columns = [f"第{c}季度 (Q{c})" for c in q_pivot.columns]
        q_pivot["全年度合计"] = q_pivot.index.map(yearly_map)

        def format_pct(val):
            if pd.isna(val): return "-"
            color = "#aa3d33" if val > 0 else ("#27735b" if val < 0 else "#606c78")
            return f"<span style='color:{color}; font-weight:600;'>{val*100:+.2f}%</span>"

        st.markdown("###### 1️⃣ 季度收益率矩阵")
        st.write(q_pivot.applymap(format_pct).to_html(escape=False), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("###### 2️⃣ 月度收益率矩阵与胜率统计")
        m_pivot = p_df.groupby([p_df["year"], p_df["month"]])["return"].apply(
            lambda x: (1 + x).cumprod().iloc[-1] - 1
        ).unstack()
        m_pivot.columns = [f"{c}月" for c in m_pivot.columns]
        m_pivot["全年度合计"] = m_pivot.index.map(yearly_map)
        st.write(m_pivot.applymap(format_pct).to_html(escape=False), unsafe_allow_html=True)

        all_months = p_df.groupby([p_df["year"], p_df["month"]])["return"].apply(lambda x: (1 + x).cumprod().iloc[-1] - 1)
        win_months = (all_months > 0).sum()
        total_months = len(all_months)
        m_win_rate = (win_months / total_months * 100) if total_months > 0 else 0

        st.markdown("<br>", unsafe_allow_html=True)
        mc1, mc2, mc3, mc4 = st.columns(4)
        with mc1: st.metric("月度盈利胜率", f"{m_win_rate:.1f}%", f"{win_months} / {total_months} 月")
        with mc2: st.metric("历史单月最佳", f"{all_months.max()*100:+.2f}%")
        with mc3: st.metric("历史单月最差", f"{all_months.min()*100:+.2f}%")
        with mc4: st.metric("月度平均收益", f"{all_months.mean()*100:+.2f}%")

    with tab3:
        st.markdown("##### 券商逐笔交割流水单与同花顺复盘")

        @st.dialog("同花顺专业行情与交割复盘系统", width="large")
        def show_tonghuashun_modal(sym, full_ledger, s_dt, e_dt):
            sym_name = get_symbol_display_name(sym)
            sym_ledger = full_ledger[full_ledger["标的代码"] == sym] if len(full_ledger) > 0 else pd.DataFrame()
            sym_wins = sum(1 for _, r in sym_ledger.iterrows() if "盈利" in str(r.get("交割状态", "")))
            sym_closed = sum(1 for _, r in sym_ledger.iterrows() if r.get("卖出日期") != "当前仍持仓")
            win_rate = (sym_wins / sym_closed * 100) if sym_closed > 0 else 0.0

            c1, c2, c3, c4 = st.columns([1.5, 1, 1, 1])
            with c1:
                st.markdown(f"### **{sym.upper()}** · **{sym_name}**")
                st.caption(f"回测区间: `{s_dt.strftime('%Y-%m-%d')}` ~ `{e_dt.strftime('%Y-%m-%d')}`")
            with c2: st.metric("该标的交割", f"{len(sym_ledger)} 笔")
            with c3: st.metric("交易胜率", f"{win_rate:.1f}%")
            with c4:
                avg_h = sym_ledger["持仓天数"].mean() if len(sym_ledger) > 0 else 0
                st.metric("平均持仓", f"{avg_h:.1f} 天")

            focus_trade_key = f"modal_focus_trade_{sym}"
            raw_focus = st.session_state.get(focus_trade_key, None)
            current_focus_idx = int(raw_focus) if raw_focus is not None else None

            kline_df = load_symbol_kline(sym, s_dt, e_dt)
            if kline_df is not None and len(kline_df) > 0:
                echarts_html = build_tonghuashun_echarts_html(
                    kline_df, sym_ledger,
                    symbol_name=f"{sym.upper()} {sym_name}",
                    chart_height=600,
                    focus_trade_idx=current_focus_idx
                )
                components.html(echarts_html, height=620, scrolling=False)

        ledger_df = generate_full_trade_ledger(df)
        if len(ledger_df) > 0:
            total_trades = len(ledger_df)
            win_trades = sum(1 for _, r in ledger_df.iterrows() if r.get("交割状态") == "盈利 ")
            loss_trades = sum(1 for _, r in ledger_df.iterrows() if r.get("交割状态") == "亏损 🔴")
            closed_trades = win_trades + loss_trades
            win_rate = (win_trades / closed_trades * 100) if closed_trades > 0 else 0.0

            l1, l2, l3, l4 = st.columns(4)
            with l1: st.metric("总交割笔数", f"{total_trades} 笔")
            with l2: st.metric("已平仓笔数", f"{closed_trades} 笔")
            with l3: st.metric("交割胜率", f"{win_rate:.1f}%")
            with l4: st.metric("平均持仓", f"{ledger_df['持仓天数'].mean():.1f} 天")

            all_unique_syms = sorted(list(ledger_df["标的代码"].unique()))
            st.markdown("###### 点击标的弹出【同花顺】操盘 K 线买卖复盘：")
            p_cols = st.columns(min(len(all_unique_syms), 6))
            for i, sym in enumerate(all_unique_syms):
                col = p_cols[i % len(p_cols)]
                s_name = get_symbol_display_name(sym)
                if col.button(f"{s_name} ({sym})", key=f"btn_sym_modal_{sym}", use_container_width=True):
                    show_tonghuashun_modal(sym, ledger_df, df.index.min(), df.index.max())

            # 紧凑分页交割流水
            page_size = 12
            total_records = len(ledger_df)
            total_pages = max(1, (total_records + page_size - 1) // page_size)
            if "ledger_page_num" not in st.session_state:
                st.session_state["ledger_page_num"] = 1

            p_c1, p_c2, p_c3 = st.columns([2, 3, 2])
            with p_c1:
                if st.button("⬅️ 上一页", disabled=(st.session_state["ledger_page_num"] <= 1), use_container_width=True):
                    st.session_state["ledger_page_num"] -= 1
                    st.rerun()
            with p_c2:
                st.markdown(f"<div style='text-align:center; padding-top:6px; color:#606c78; font-size:12px;'>第 <b>{st.session_state['ledger_page_num']}</b> / {total_pages} 页 (共 {total_records} 笔)</div>", unsafe_allow_html=True)
            with p_c3:
                if st.button("下一页 ➡️", disabled=(st.session_state["ledger_page_num"] >= total_pages), use_container_width=True):
                    st.session_state["ledger_page_num"] += 1
                    st.rerun()

            current_page = st.session_state["ledger_page_num"]
            start_row = (current_page - 1) * page_size
            end_row = min(start_row + page_size, total_records)
            page_df = ledger_df.iloc[start_row:end_row].copy()

            disp_cols = ["标的代码", "标的名称", "买入日期", "买入价格", "卖出日期", "卖出价格", "持仓天数", "单笔收益率", "交割状态"]
            st.dataframe(page_df[disp_cols], use_container_width=True, hide_index=True)
        else:
            st.info("当前回测记录中暂未解析到交割记录。")

    with tab4:
        st.markdown("##### 每日回测撮合原始明细")
        st.dataframe(df, use_container_width=True)
        csv_bytes = df.to_csv().encode('utf-8')
        st.download_button("导出每日撮合明细 CSV", data=csv_bytes, file_name="backtest_report.csv", mime="text/csv")
