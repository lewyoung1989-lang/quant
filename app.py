#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股 AI 量化投研与交易台 Web UI (Streamlit)
第二版专业交易台布局重构规范 (Workbench Layout 2.0)
严格遵循 HANDOFF.md 与 preview-desktop.png 设计语言
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
from services.rebalance_service import (
    get_all_accounts,
    get_current_position,
    save_current_position,
    generate_rebalance_plan,
    record_trade_log,
    get_trade_logs,
    execute_simulated_rebalance
)
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
    page_title="量化回测台 · 策略研究与模拟交易",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 报表文件路径常量
REPORT_CSV = "./reports/backtest_daily_report.csv"
FACTOR_REPORT_CSV = "./reports/factor_backtest_report.csv"
TWIN_BOND_REPORT_CSV = "./reports/twin_bond_report.csv"

def render_html(html_str: str):
    """
    渲染 HTML 并消除每行首尾多余空白，彻底杜绝 Markdown 将 4 空格以上缩进误解析为 <pre><code> 源码块
    """
    cleaned = "\n".join(line.strip() for line in html_str.strip().split("\n") if line.strip())
    st.markdown(cleaned, unsafe_allow_html=True)

# ==========================================
# 注入交易台专业浅色 CSS (workbench.css 规范)
# ==========================================
st.markdown(
    """
    <style>
    /* 核心调色板与全局基调 */
    :root {
        --bg: #f4f5f6;
        --paper: #ffffff;
        --ink: #202b36;
        --muted: #606c78;
        --line: #d8dee4;
        --line-subtle: #edf1f4;
        --accent: #285873;
        --accent-soft: #eaf0f4;
        --pos: #aa3d33;
        --neg: #27735b;
    }

    /* 页面背景与正文宽度控制 (最大1260px，桌面优先) */
    .stApp {
        background-color: var(--bg);
        color: var(--ink);
        font-size: 13px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    }

    .main .block-container {
        max-width: 1260px;
        padding: 16px 28px 40px 28px;
    }

    /* 侧边栏专业样式 (218px ~ 250px 宽参考) */
    [data-testid="stSidebar"] {
        background-color: #edf0f3;
        border-right: 1px solid #cbd3da;
    }

    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.65rem;
    }

    /* 侧边栏顶部品牌 */
    .brand-box {
        padding: 4px 2px 14px 2px;
        border-bottom: 1px solid #cbd3da;
        margin-bottom: 10px;
    }
    .brand-title {
        font-size: 17px;
        font-weight: 700;
        color: #202b36;
        letter-spacing: -0.01em;
    }
    .brand-sub {
        font-size: 11px;
        color: #606c78;
        margin-top: 2px;
    }

    /* 侧边栏工作模式单选框 - 紧凑交易终端样式 */
    [data-testid="stSidebar"] .stRadio > label {
        font-size: 11px;
        color: #606c78;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 4px;
    }

    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] {
        gap: 3px;
    }

    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label {
        background: transparent;
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 7px 10px;
        font-size: 13px;
        font-weight: 500;
        color: #4b5768;
        cursor: pointer;
        transition: all 0.15s ease;
    }

    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:hover {
        background: #e1e7ec;
    }

    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:has(input:checked) {
        background: #ffffff;
        border-color: #cbd3da;
        color: #202b36;
        font-weight: 600;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }

    /* 侧边栏字段标题紧凑化 */
    [data-testid="stSidebar"] h3 {
        font-size: 12px !important;
        font-weight: 650 !important;
        color: var(--ink) !important;
        margin: 12px 0 6px 0 !important;
        padding-top: 6px;
        border-top: 1px solid #cbd3da;
    }

    /* 顶栏面包屑与状态徽标 */
    .top-crumb-bar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding-bottom: 12px;
        margin-bottom: 16px;
        border-bottom: 1px solid var(--line);
        font-size: 11px;
        color: var(--muted);
    }
    .crumb-left strong {
        color: var(--ink);
        font-weight: 600;
    }
    .crumb-badge {
        background: #eef1f5;
        border: 1px solid #d8dee4;
        padding: 2px 7px;
        border-radius: 3px;
        font-size: 10px;
        color: #556371;
    }

    /* 页面标题头 */
    .page-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 18px;
    }
    .page-head h1 {
        font-size: 21px;
        font-weight: 650;
        color: var(--ink);
        margin: 0;
        line-height: 1.3;
    }
    .page-head p {
        font-size: 12px;
        color: var(--muted);
        margin: 4px 0 0 0;
    }

    /* 浅底决策条 (Decision Banner) */
    .decision-banner {
        background: #f7fafb;
        border: 1px solid #afbdc7;
        border-radius: 0px;
        padding: 16px 20px;
        display: grid;
        grid-template-columns: minmax(0, 1fr) 230px;
        gap: 20px;
        margin-bottom: 18px;
    }
    .decision-main h2 {
        font-size: 19px;
        font-weight: 650;
        margin: 6px 0 4px 0;
        color: var(--ink);
    }
    .decision-main p {
        font-size: 12px;
        color: #53616d;
        margin: 0;
        line-height: 1.5;
    }
    .decision-time-box {
        border-left: 1px solid #afbdc7;
        padding-left: 20px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .decision-time-box small {
        font-size: 11px;
        color: #53616d;
    }
    .decision-time-box strong {
        font-size: 19px;
        font-weight: 700;
        color: #856121;
        margin: 4px 0;
        letter-spacing: 0.5px;
    }
    .decision-time-box .time-stamp {
        font-size: 10px;
        color: #687482;
    }

    /* 账户概况条 (Account Strip / Ledger) */
    .account-strip {
        background: #ffffff;
        border: 1px solid var(--line);
        display: grid;
        grid-template-columns: 1.3fr 1.1fr 1.1fr 1fr 1fr;
        padding: 0;
        margin-bottom: 20px;
    }
    .account-cell {
        padding: 12px 16px;
        border-left: 1px solid var(--line);
    }
    .account-cell:first-child {
        border-left: none;
        background: #fafbfc;
    }
    .account-cell .acc-label {
        font-size: 11px;
        color: var(--muted);
        margin-bottom: 3px;
    }
    .account-cell .acc-val {
        font-size: 19px;
        font-weight: 600;
        color: var(--ink);
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.01em;
    }
    .account-cell .acc-tag {
        font-size: 10px;
        margin-top: 3px;
    }

    /* 委托表面板 */
    .panel-box {
        background: #ffffff;
        border: 1px solid var(--line);
        border-radius: 0;
        margin-bottom: 12px;
    }
    .panel-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 16px;
        border-bottom: 1px solid var(--line);
        background: #ffffff;
    }
    .panel-header h2 {
        font-size: 14px;
        font-weight: 650;
        margin: 0;
        color: var(--ink);
    }
    .panel-header small {
        font-size: 11px;
        color: var(--muted);
    }

    /* 纯 HTML 委托清单表格 */
    .table-wrap {
        overflow-x: auto;
    }
    table.workbench-table {
        border-collapse: collapse;
        width: 100%;
        font-size: 12px;
        white-space: nowrap;
    }
    table.workbench-table th {
        text-align: left;
        color: var(--muted);
        font-weight: 500;
        font-size: 11px;
        background: #f7f8f9;
        padding: 11px 16px;
        border-bottom: 1px solid var(--line);
    }
    table.workbench-table td {
        padding: 14px 16px;
        border-bottom: 1px solid var(--line);
        color: var(--ink);
    }
    table.workbench-table td.n, table.workbench-table th.n {
        text-align: right;
        font-variant-numeric: tabular-nums;
    }
    table.workbench-table td b {
        font-weight: 600;
    }
    table.workbench-table td small {
        display: block;
        font-size: 10px;
        color: var(--muted);
        margin-top: 2px;
    }

    .order-summary-bar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 11px 16px;
        font-size: 11px;
        color: var(--muted);
        background: #ffffff;
    }

    /* 执行条 - 紧贴表格底部 */
    .exec-card {
        padding: 12px 16px;
        border-top: 1px solid var(--line);
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 16px;
    }
    .exec-card.disabled {
        background: #faf8f1;
    }
    .exec-card.active {
        background: #f3f9f3;
    }
    .exec-card strong {
        font-size: 12px;
        display: block;
    }
    .exec-card p {
        font-size: 11px;
        margin: 2px 0 0 0;
    }
    .exec-card.disabled strong, .exec-card.disabled p {
        color: #7b5c26;
    }
    .exec-card.active strong, .exec-card.active p {
        color: #207959;
    }

    /* 右侧行情栏 */
    .market-rail-box {
        background: #ffffff;
        border: 1px solid var(--line);
        border-top: 2px solid #8e9eab;
        padding: 14px 16px;
    }
    .rail-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--line);
        margin-bottom: 12px;
    }
    .rail-header h2 {
        font-size: 13px;
        font-weight: 650;
        margin: 0;
        color: var(--ink);
    }
    .rail-header small {
        font-size: 10px;
        color: var(--muted);
    }
    .quote-item {
        padding: 10px 0;
        border-bottom: 1px solid var(--line-subtle);
    }
    .quote-item:last-of-type {
        border-bottom: 1px solid var(--line);
    }
    .quote-top-line {
        display: flex;
        justify-content: space-between;
        font-size: 11px;
    }
    .quote-bot-line {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        margin-top: 4px;
    }
    .quote-bot-line strong {
        font-size: 20px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        color: var(--ink);
    }

    .pos { color: var(--pos) !important; }
    .neg { color: var(--neg) !important; }

    /* 研报卡片与占位符 */
    .research-note-bar {
        display: flex;
        gap: 24px;
        padding: 11px 16px;
        background: #ffffff;
        border: 1px solid var(--line);
        font-size: 11px;
        color: var(--muted);
        margin-bottom: 18px;
    }
    .research-note-bar b {
        color: var(--ink);
        font-weight: 600;
    }

    .empty-placeholder {
        padding: 48px 24px;
        text-align: center;
        background: #ffffff;
        border: 1px solid var(--line);
    }
    .empty-placeholder h2 {
        font-size: 16px;
        font-weight: 650;
        margin: 0 0 6px 0;
        color: var(--ink);
    }
    .empty-placeholder p {
        font-size: 12px;
        color: var(--muted);
        margin: 0 auto 16px auto;
        max-width: 50ch;
    }

    /* 页脚 */
    .workbench-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-top: 26px;
        padding-top: 14px;
        border-top: 1px solid var(--line);
        font-size: 11px;
        color: var(--muted);
    }

    /* 侧边栏底部说明 */
    .source-note {
        margin-top: 24px;
        padding-top: 12px;
        border-top: 1px solid #cbd3da;
        font-size: 10px;
        color: var(--muted);
        line-height: 1.5;
    }
    .source-note b {
        color: var(--ink);
        display: block;
        font-size: 11px;
        margin-bottom: 2px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ==========================================
# 侧边栏：品牌与模式切换 (左侧 218px 规范)
# ==========================================
with st.sidebar:
    st.markdown(
        """
        <div class="brand-box">
            <div class="brand-title">量化回测台</div>
            <div class="brand-sub">策略研究与模拟交易</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 四大短名称模式入口
    strategy_mode = st.radio(
        "工作模式",
        ["今日调仓", "攻守轮动", "因子实验", "模型回测"],
        index=0,
        label_visibility="visible"
    )

# 通用标的池映射字典
universe_options = {
    "csi300": "沪深300股票池",
    "csi500": "中证500股票池",
    "etf": "指数 ETF 核心轮动池"
}

# ==========================================
# 模式一：今日调仓 (实盘盯盘与模拟委托)
# ==========================================
if strategy_mode == "今日调仓":
    all_accs = get_all_accounts()
    acc_names = list(all_accs.keys())

    # 1. 侧边栏：今日调仓专属参数
    with st.sidebar:
        st.markdown("### 调仓设置")
        sel_acc = st.selectbox("模拟账户", acc_names, index=0)

        live_tech_opts = {
            "sz159915": "创业板ETF · 159915",
            "sh588380": "双创50ETF · 588380"
        }
        live_def_opts = {
            "sh512890": "红利低波ETF · 512890",
            "sh511010": "国债ETF · 511010"
        }

        acc_obj = all_accs.get(sel_acc, {})
        def_tech_key = acc_obj.get("tech_symbol", "sz159915" if "1" in sel_acc else "sh588380")
        def_def_key = acc_obj.get("def_symbol", "sh512890" if "1" in sel_acc else "sh511010")

        tech_idx = list(live_tech_opts.keys()).index(def_tech_key) if def_tech_key in live_tech_opts else 0
        def_idx = list(live_def_opts.keys()).index(def_def_key) if def_def_key in live_def_opts else 0

        cur_tech = st.selectbox("进攻标的", list(live_tech_opts.keys()), format_func=lambda x: live_tech_opts[x], index=tech_idx)
        cur_def = st.selectbox("防守标的", list(live_def_opts.keys()), format_func=lambda x: live_def_opts[x], index=def_idx)
        cur_window = st.slider("动量周期", min_value=5, max_value=60, value=int(acc_obj.get("lookback_window", 20)), step=5)

        # 低频折叠一：账户与自动调仓
        with st.expander("账户与自动调仓"):
            auto_trade_toggle = st.toggle("尾盘自动模拟调仓", value=acc_obj.get("auto_trade", True), help="仅在 14:45–14:55 时间窗触发自动撮合。")
            if auto_trade_toggle != acc_obj.get("auto_trade", True):
                acc_obj["auto_trade"] = auto_trade_toggle
                save_current_position(acc_obj, account_name=sel_acc)

            new_acc_name = st.text_input("新建账户名称", placeholder="例如: 稳健攻守 3 号")
            init_cap = st.number_input("初始虚拟资金 (元)", value=100000.0, step=10000.0)
            if st.button("新建模拟账户", use_container_width=True):
                if new_acc_name.strip():
                    save_current_position({
                        "initial_capital": float(init_cap),
                        "holding_symbol": "",
                        "holding_amount": 0,
                        "cash_available": float(init_cap),
                        "tech_symbol": cur_tech,
                        "def_symbol": cur_def,
                        "lookback_window": cur_window,
                        "auto_trade": auto_trade_toggle
                    }, account_name=new_acc_name.strip())
                    st.toast(f"已创建账户: {new_acc_name.strip()}", icon="✅")
                    st.rerun()

            st.markdown("---")
            if st.button("🔄 重置当前账户资金为 10 万元", use_container_width=True, help="清空当前持仓，并将可用资金重置为初始 10 万元。"):
                save_current_position({
                    "initial_capital": 100000.0,
                    "holding_symbol": "",
                    "holding_amount": 0,
                    "cash_available": 100000.0,
                    "tech_symbol": cur_tech,
                    "def_symbol": cur_def,
                    "lookback_window": cur_window,
                    "auto_trade": auto_trade_toggle
                }, account_name=sel_acc)
                st.toast(f"已重置【{sel_acc}】为 10 万元现金待命状态！", icon="🔄")
                st.rerun()

        # 低频折叠二：更多设置 · 费率与基准
        with st.expander("更多设置 · 费率与基准"):
            benchmark = st.text_input("基准标的", "SH000300")
            open_cost_bp = st.number_input("买入佣金 (万分之)", value=1.0, step=0.5)
            close_cost_bp = st.number_input("卖出费率 (万分之)", value=1.0, step=0.5)
            st.caption("ETF 免征印花税，仅收取券商佣金 (通常为万1)。")

        st.markdown(
            """
            <div class="source-note">
                <b>数据来源</b>
                Qlib 历史数据 · 新浪实时行情<br>
                实盘交易请遵循合规与风险管理
            </div>
            """,
            unsafe_allow_html=True
        )

    # 顶栏面包屑
    st.markdown(
        """
        <div class="top-crumb-bar">
            <span class="crumb-left"><strong>模拟交易</strong> / <span>今日调仓</span></span>
            <span class="crumb-badge">实盘监控 · 模拟撮合</span>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 头部标题与“刷新行情”按钮
    c_head_left, c_head_right = st.columns([4, 1])
    now_dt = datetime.datetime.now()
    weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    date_str = f"{now_dt.year} 年 {now_dt.month:02d} 月 {now_dt.day:02d} 日　{weekday_cn[now_dt.weekday()]}"

    with c_head_left:
        st.markdown(
            f"""
            <div class="page-head" style="margin-bottom:0;">
                <div>
                    <h1>今日调仓</h1>
                    <p>{date_str}</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with c_head_right:
        st.write("")
        refresh_clicked = st.button("刷新行情", use_container_width=True)

    # 优化点 3：行情数据 5 秒短期缓存，点击“刷新行情”时强制打透
    if "refresh_seq" not in st.session_state:
        st.session_state["refresh_seq"] = 0

    if refresh_clicked:
        st.cache_data.clear()
        st.session_state["refresh_seq"] += 1
        st.toast("最新行情已刷新！", icon="🔄")

    # 读取/计算调仓方案
    @st.cache_data(ttl=5, show_spinner=False)
    def _fetch_plan_cached(tech, defense, window, acc, seq):
        return generate_rebalance_plan(tech, defense, window, account_name=acc)

    plan = _fetch_plan_cached(cur_tech, cur_def, cur_window, sel_acc, st.session_state["refresh_seq"])
    sig = plan["signal"]
    port = plan["portfolio"]
    orders = plan["orders"]
    pos = plan["position"]
    init_capital = float(pos.get("initial_capital", 100000.0))
    total_return_pct = ((port["total_assets"] - init_capital) / init_capital) * 100

    # 自动调仓检测与撮合
    if auto_trade_toggle:
        exec_res = execute_simulated_rebalance(sel_acc, cur_tech, cur_def, cur_window)
        if exec_res.get("executed"):
            st.toast(f"自动调仓已执行: {exec_res['message']}", icon="🚀")

    # 优化点 4：根据当前时间显式区分状态
    now_hour = now_dt.hour
    now_minute = now_dt.minute
    is_trade_day = now_dt.weekday() < 5
    in_exec_window = is_trade_day and (now_hour == 14 and 45 <= now_minute <= 55)
    is_intraday = is_trade_day and ((9 <= now_hour < 11 or (now_hour == 11 and now_minute <= 30)) or (13 <= now_hour < 15))

    if in_exec_window:
        status_tag_html = '<span class="decision-status-tag pos"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:#aa3d33;margin-right:5px;"></span>🔥 尾盘窗口 · 允许调仓确认</span>'
    elif is_intraday:
        status_tag_html = '<span class="decision-status-tag" style="color:#856121;"><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#9d762f;margin-right:5px;"></span>● 盘中监控 · 以尾盘确认结果为准</span>'
    else:
        status_tag_html = '<span class="decision-status-tag" style="color:#606c78;"><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#8e9eab;margin-right:5px;"></span>⚪ 休市盘后 · 历史收盘定型</span>'

    # 2. 浅底决策条 (Decision Banner)
    action_text = plan['summary_action']
    quote_time = sig['tech'].get('quote_time', now_dt.strftime('%H:%M:%S'))
    st.markdown(
        f"""
        <section class="decision-banner" aria-label="今日决策">
            <div class="decision-main">
                {status_tag_html}
                <h2>{action_text}</h2>
                <p>{plan['reason']}</p>
            </div>
            <div class="decision-time-box">
                <small>模拟调仓时间</small>
                <strong>14:45–14:55</strong>
                <p class="time-stamp">行情更新于 {quote_time}</p>
            </div>
        </section>
        """,
        unsafe_allow_html=True
    )

    # 3. 紧凑账户概况条 (Account Strip)
    ret_color_cls = "pos" if total_return_pct > 0 else ("neg" if total_return_pct < 0 else "")
    ret_sign = "+" if total_return_pct > 0 else ""
    holding_desc = port['current_holding_name'] if port['current_holding_name'] else "空仓"

    st.markdown(
        f"""
        <section class="account-strip" aria-label="账户概况">
            <div class="account-cell">
                <div class="acc-label"><strong>{sel_acc}</strong></div>
                <div class="acc-tag" style="color:#606c78;">账户概况</div>
            </div>
            <div class="account-cell">
                <div class="acc-label">总资产</div>
                <div class="acc-val">¥{port['total_assets']:,.2f}</div>
            </div>
            <div class="account-cell">
                <div class="acc-label">可用现金</div>
                <div class="acc-val">¥{port['cash']:,.2f}</div>
            </div>
            <div class="account-cell">
                <div class="acc-label">当前持仓</div>
                <div class="acc-val" style="font-size:16px;">{holding_desc}</div>
            </div>
            <div class="account-cell">
                <div class="acc-label">累计收益</div>
                <div class="acc-val {ret_color_cls}">{ret_sign}{total_return_pct:.2f}%</div>
            </div>
        </section>
        """,
        unsafe_allow_html=True
    )

    # 4. 双栏交易工作区 (Split Layout)
    col_main, col_rail = st.columns([1.65, 1.0], gap="medium")

    # A. 左侧主区：调仓委托清单 + 尾盘执行按钮
    with col_main:
        real_trades = [o for o in orders if o.get("action") in ["买入", "卖出"]]

        if real_trades:
            order_rows_html = ""
            for o in real_trades:
                action_cls = "pos" if o["action"] == "买入" else "neg"
                sym_upper = o["symbol"].upper()
                order_rows_html += f"<tr><td><b class='{action_cls}'>{o['action']}</b></td><td><b>{o['name']}</b><small>{sym_upper}</small></td><td class='n'>{o['shares']:,}</td><td class='n'>{o['price']:.3f}</td><td class='n'>{o['est_amount']:,.2f}</td></tr>"

            render_html(
                f"""
                <div class="panel-box">
                    <div class="panel-header">
                        <h2>调仓清单</h2>
                        <small>{len(real_trades)} 笔委托 · 模拟交易</small>
                    </div>
                    <div class="table-wrap">
                        <table class="workbench-table">
                            <thead>
                                <tr>
                                    <th>方向</th>
                                    <th>证券名称 / 代码</th>
                                    <th class="n">数量（股）</th>
                                    <th class="n">参考价</th>
                                    <th class="n">预计金额</th>
                                </tr>
                            </thead>
                            <tbody>
                                {order_rows_html}
                            </tbody>
                        </table>
                    </div>
                    <div class="order-summary-bar">
                        <span>预计金额未含费用；以实际模拟撮合结果为准。</span>
                        <span style="color:#856121; font-weight:600;">{'尾盘待执行' if in_exec_window else '待尾盘执行'}</span>
                    </div>
                </div>
                """
            )

            # 紧贴表格底部的执行区域
            if in_exec_window:
                exec_card_class = "active"
                exec_title = "当前处于尾盘决策窗口 (14:45–14:55)"
                exec_desc = "价格已进入终盘定型阶段，系统可执行确定性换仓！"
            else:
                exec_card_class = "disabled"
                exec_title = "尚未进入执行时间"
                exec_desc = f"当前为盘中监控期 (现时间 {now_dt.strftime('%H:%M:%S')})，策略严格规定 14:45–14:55 方可执行调仓。"

            c_info, c_btn = st.columns([2.5, 1.3])
            with c_info:
                render_html(
                    f"""
                    <div class="exec-card {exec_card_class}" style="border: 1px solid var(--line); margin-top:-6px; border-radius:0;">
                        <div>
                            <strong>{exec_title}</strong>
                            <p>{exec_desc}</p>
                        </div>
                    </div>
                    """
                )
            with c_btn:
                st.write("")
                btn_help = "已在 14:45~14:55 窗口内，点击立即模拟调仓" if in_exec_window else "当前未在 14:45~14:55 窗口内，按钮已禁用"
                if st.button("执行模拟调仓", type="primary" if in_exec_window else "secondary", disabled=not in_exec_window, help=btn_help, use_container_width=True):
                    # 模拟卖出
                    sells = [o for o in real_trades if o["action"] == "卖出"]
                    for s in sells:
                        record_trade_log(sel_acc, "卖出平仓", s["symbol"], s["shares"], s["price"], s["est_amount"], reason="尾盘动量切换平仓")
                    # 模拟买入
                    buys = [o for o in real_trades if o["action"] == "买入"]
                    last_b = buys[-1] if buys else None
                    if last_b:
                        remain_cash = port['total_assets'] - last_b['est_amount']
                        save_current_position({
                            "initial_capital": init_capital,
                            "holding_symbol": last_b["symbol"],
                            "holding_amount": int(last_b["shares"]),
                            "cash_available": max(0.0, round(remain_cash, 2)),
                            "tech_symbol": cur_tech,
                            "def_symbol": cur_def,
                            "lookback_window": cur_window,
                            "auto_trade": auto_trade_toggle
                        }, account_name=sel_acc)
                        record_trade_log(sel_acc, "买入建仓", last_b["symbol"], last_b["shares"], last_b["price"], last_b["est_amount"], reason="尾盘动量切换建仓")
                        st.success(f"模拟调仓执行成功！已全额建仓持有：{last_b['name']} ({last_b['shares']:,} 股)！")
                        st.rerun()

        else:
            # 优化点 2：无需调仓时的专属展示态 (区分空仓观望 vs 现有持仓)
            hold_name = port['current_holding_name'] if port['current_holding_name'] else "空仓"
            hold_shares = pos.get('holding_amount', 0)
            hold_mv = port['market_value']
            target_name = ETF_POOL.get(sig['target_symbol'], sig['target_symbol']).split()[0]
            setup_o = plan.get("setup_order", {})

            if hold_shares > 0:
                card_icon = "✅"
                card_title = f"持仓与目标一致 · 今日保持现有持仓"
                card_desc = f"当前持有 <b>{hold_name}</b> ({hold_shares:,} 股 / 市值 ¥{hold_mv:,.2f})，今日无新变盘信号，无需进行任何换仓操作。"
                exec_title = "保持现有持仓"
                exec_desc = "尾盘无需进行调仓下单，继续享受当前标的趋势收益。"
                btn_text = "无需调仓"
            else:
                card_icon = "⚪"
                card_title = "保持空仓观望 · 今日无新变盘信号"
                card_desc = f"当前策略延续【{target_name}】防守周期，今日进攻与防守信号未发生切换。建议保持空仓观望，等待下一次变盘信号出现。"
                exec_title = "保持空仓观望"
                exec_desc = "今日未触发新变盘信号，保持空仓状态，无需调仓委托。"
                btn_text = "无需调仓 (保持空仓)"

            render_html(
                f"""
                <div class="panel-box">
                    <div class="panel-header">
                        <h2>调仓清单</h2>
                        <small>{'当前持仓与信号一致' if hold_shares > 0 else '空仓观望'} · 无需委托</small>
                    </div>
                    <div style="padding: 24px 20px; background: #ffffff;">
                        <div style="display:flex; align-items:center; gap:12px; margin-bottom:12px;">
                            <span style="font-size:20px;">{card_icon}</span>
                            <div>
                                <b style="font-size:13px; color:#202b36;">{card_title}</b>
                                <p style="font-size:12px; color:#606c78; margin:2px 0 0 0;">
                                    {card_desc}
                                </p>
                            </div>
                        </div>
                    </div>
                    <div class="exec-card active" style="border-top:1px solid var(--line);">
                        <div>
                            <strong>{exec_title}</strong>
                            <p>{exec_desc}</p>
                        </div>
                        <button class="stButton" disabled style="background:#eaf0f4; border:1px solid #d8dee4; border-radius:3px; padding:6px 12px; font-size:12px; color:#77808d; cursor:not-allowed;">{btn_text}</button>
                    </div>
                </div>
                """
            )

            # 若用户为空仓且希望手动跟单开启底仓，提供非侵入式的可选建仓入口
            if hold_shares == 0 and setup_o.get("shares", 0) > 0:
                with st.expander("🛒 若需跟随策略开启底仓，点击可手动建仓", expanded=False):
                    st.caption(f"当前策略目标为【{target_name}】。点击下方按钮可立即使用可用现金（¥{port['cash']:,.2f}）建立模拟底仓（约 {setup_o['shares']:,} 股，预估金额 ¥{setup_o['est_amount']:,.2f}）。")
                    if st.button(f"手动建立底仓 · 买入【{target_name}】", type="secondary", use_container_width=True):
                        remain_cash = port['total_assets'] - setup_o['est_amount']
                        save_current_position({
                            "initial_capital": init_capital,
                            "holding_symbol": setup_o["symbol"],
                            "holding_amount": int(setup_o["shares"]),
                            "cash_available": max(0.0, round(remain_cash, 2)),
                            "tech_symbol": cur_tech,
                            "def_symbol": cur_def,
                            "lookback_window": cur_window,
                            "auto_trade": auto_trade_toggle
                        }, account_name=sel_acc)
                        record_trade_log(sel_acc, "手动建仓", setup_o["symbol"], setup_o["shares"], setup_o["price"], setup_o["est_amount"], reason="用户手动跟单建立初始底仓")
                        st.success(f"已手动为【{sel_acc}】建立底仓：{target_name} ({setup_o['shares']:,} 股)！")
                        st.rerun()

        st.caption("此环境为模拟实盘撮合，在 14:45–14:55 时间窗内点击执行将记入账户流水。")

        # 底部折叠：历史调仓记录
        with st.expander("▶ 历史调仓记录", expanded=False):
            acc_logs = get_trade_logs(account_name=sel_acc)
            if acc_logs:
                st.dataframe(pd.DataFrame(acc_logs), use_container_width=True, hide_index=True)
            else:
                render_html(
                    """
                    <div style="background:#fff; border:1px solid var(--line); padding:16px; font-size:12px;">
                        <b>暂无调仓记录</b>
                        <p style="color:#606c78; font-size:11px; margin-top:4px;">执行模拟调仓后，这里将显示时间、标的、数量、价格与成交金额流水。</p>
                    </div>
                    """
                )

    # B. 右侧栏：行情与信号栏 (250px 宽参考)
    with col_rail:
        t_mom = sig['tech']['mom'] * 100
        d_mom = sig['defensive']['mom'] * 100
        t_cls = "pos" if t_mom >= 0 else "neg"
        d_cls = "pos" if d_mom >= 0 else "neg"
        t_sign = "+" if t_mom >= 0 else ""
        d_sign = "+" if d_mom >= 0 else ""

        # 优化点 1：变盘距离与安全边际测算
        mom_diff = t_mom - d_mom
        ma_diff = ((sig['tech']['price'] - sig['tech']['ma']) / sig['tech']['ma']) * 100
        is_tech_target = (sig['target_symbol'].lower() == cur_tech.lower())

        if is_tech_target:
            trigger_summary = f"进攻动量领先防守 <b>{mom_diff:+.2f}%</b>，站上均线 <b>{ma_diff:+.2f}%</b>，满足全部进攻条件。"
        else:
            trigger_summary = f"进攻动量较防守落后 <b>{abs(mom_diff):.2f}%</b>，距 20 日均线 <b>{ma_diff:+.2f}%</b>，当前保持防守配置。"

        render_html(
            f"""
            <aside class="market-rail-box" aria-label="信号与行情">
                <div class="rail-header">
                    <h2>行情与信号</h2>
                    <small>{cur_window} 日动量</small>
                </div>
                <div class="quote-item">
                    <div class="quote-top-line">
                        <span>{live_tech_opts.get(cur_tech, cur_tech).split()[0]}</span>
                        <small style="color:#606c78;">进攻 / {cur_tech.upper()}</small>
                    </div>
                    <div class="quote-bot-line">
                        <strong>{sig['tech']['price']:.3f}</strong>
                        <span class="{t_cls}" style="font-size:13px; font-weight:600;">{t_sign}{t_mom:.2f}%</span>
                    </div>
                </div>
                <div class="quote-item">
                    <div class="quote-top-line">
                        <span>{live_def_opts.get(cur_def, cur_def).split()[0]}</span>
                        <small style="color:#606c78;">防守 / {cur_def.upper()}</small>
                    </div>
                    <div class="quote-bot-line">
                        <strong>{sig['defensive']['price']:.3f}</strong>
                        <span class="{d_cls}" style="font-size:13px; font-weight:600;">{d_sign}{d_mom:.2f}%</span>
                    </div>
                </div>
                <div style="padding-top:14px;">
                    <h3 style="font-size:12px; font-weight:650; margin:0 0 4px 0; color:#202b36;">本次判断</h3>
                    <p style="font-size:11px; color:#53616d; line-height:1.6; margin:0 0 8px 0;">{trigger_summary}</p>
                </div>
            </aside>
            """
        )

        with st.expander("▶ 查看规则与数据质量", expanded=False):
            st.markdown("##### 动量规则检测")
            for k, v in sig["conditions"].items():
                icon = "🟢 通过" if v["passed"] else "🔴 未通过"
                st.markdown(f"- {icon}: {v['name']}")

            st.caption(f"""
            **计算依据**:
            - 进攻动量: `{t_sign}{t_mom:.2f}%`
            - 防守动量: `{d_sign}{d_mom:.2f}%`
            - 进攻20日均线: `¥{sig['tech']['ma']:.3f}`
            """)

            st.markdown("##### 行情数据质量")
            t_age = sig['tech'].get('age_seconds', 0)
            d_age = sig['defensive'].get('age_seconds', 0)
            st.markdown(f"- 进攻行情时效: **{t_age} 秒前** ({'正常 🟢' if t_age < 60 else '延迟 ⚠️'})")
            st.markdown(f"- 防守行情时效: **{d_age} 秒前** ({'正常 🟢' if d_age < 60 else '延迟 ⚠️'})")

    # 页脚
    render_html(
        """
        <footer class="workbench-footer">
            <span>实盘模拟环境 · 参数与交易委托遵循策略门禁，未授权第三方交易接口</span>
            <span style="color:#606c78;">新浪财经实时行情直通</span>
        </footer>
        """
    )

# ==========================================
# 模式二：攻守轮动 (双资产动量趋势回测)
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

    with st.sidebar:
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

    # 顶栏面包屑
    st.markdown(
        """
        <div class="top-crumb-bar">
            <span class="crumb-left"><strong>策略研究</strong> / <span>攻守轮动</span></span>
            <span class="crumb-badge">历史回测 · 仿真撮合</span>
        </div>
        """,
        unsafe_allow_html=True
    )

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
                <p>设置左侧标的与日期，点击右上角运行回测。报告将在当前页面展示。</p>
                <span class="crumb-badge">尚未运行</span>
            </div>
            """,
            unsafe_allow_html=True
        )

# ==========================================
# 模式三：因子实验 (自定义表达式与经典选股)
# ==========================================
elif strategy_mode == "因子实验":
    with st.sidebar:
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

    # 顶栏面包屑
    st.markdown(
        """
        <div class="top-crumb-bar">
            <span class="crumb-left"><strong>策略研究</strong> / <span>因子实验</span></span>
            <span class="crumb-badge">截面因子 · 在线回测</span>
        </div>
        """,
        unsafe_allow_html=True
    )

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
    with st.sidebar:
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

    # 顶栏面包屑
    st.markdown(
        """
        <div class="top-crumb-bar">
            <span class="crumb-left"><strong>策略研究</strong> / <span>模型回测</span></span>
            <span class="crumb-badge">机器学习 · LightGBM</span>
        </div>
        """,
        unsafe_allow_html=True
    )

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
        "📊 净值走势与风险",
        "📅 周期收益剖析 (年/季/月)",
        "🧾 券商逐笔交割与同花顺复盘",
        "📋 每日撮合明细流水"
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
            go.Scatter(x=df.index, y=df["strat_cum"], mode="lines", name="⭐ 轮动策略净值", line=dict(color="#aa3d33", width=2.6)),
            row=1, col=1
        )

        if "asset1_ret" in df.columns:
            a1_name = df["asset1_name"].iloc[0] if "asset1_name" in df.columns else "进攻标的纯持有"
            fig.add_trace(
                go.Scatter(x=df.index, y=(1 + df["asset1_ret"]).cumprod(), mode="lines", name=f"🚀 {a1_name}", line=dict(color="#d97736", width=1.6, dash="dot")),
                row=1, col=1
            )
        if "asset2_ret" in df.columns:
            a2_name = df["asset2_name"].iloc[0] if "asset2_name" in df.columns else "防守标的纯持有"
            fig.add_trace(
                go.Scatter(x=df.index, y=(1 + df["asset2_ret"]).cumprod(), mode="lines", name=f"🛡️ {a2_name}", line=dict(color="#6c5b7b", width=1.6, dash="dashdot")),
                row=1, col=1
            )

        fig.add_trace(
            go.Scatter(x=df.index, y=df["bench_cum"], mode="lines", name="📌 基准指数 (沪深300)", line=dict(color="#285873", width=1.5, dash="dash")),
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
        st.markdown("##### 📅 分年度收益率剖析 (Annual Breakdown)")
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
                "胜负状态": "跑赢基准 🟢" if yr_alpha > 0 else "跑输基准 🔴"
            })
        if yearly_records:
            st.dataframe(pd.DataFrame(yearly_records), use_container_width=True, hide_index=True)

    with tab2:
        st.markdown("##### 📅 历史周期收益率全景剖析 (年 / 季 / 月)")
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
        st.markdown("##### 🧾 券商逐笔交割流水单与同花顺复盘")

        @st.dialog("📊 同花顺专业行情与交割复盘系统", width="large")
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
            win_trades = sum(1 for _, r in ledger_df.iterrows() if r.get("交割状态") == "盈利 🟢")
            loss_trades = sum(1 for _, r in ledger_df.iterrows() if r.get("交割状态") == "亏损 🔴")
            closed_trades = win_trades + loss_trades
            win_rate = (win_trades / closed_trades * 100) if closed_trades > 0 else 0.0

            l1, l2, l3, l4 = st.columns(4)
            with l1: st.metric("总交割笔数", f"{total_trades} 笔")
            with l2: st.metric("已平仓笔数", f"{closed_trades} 笔")
            with l3: st.metric("交割胜率", f"{win_rate:.1f}%")
            with l4: st.metric("平均持仓", f"{ledger_df['持仓天数'].mean():.1f} 天")

            all_unique_syms = sorted(list(ledger_df["标的代码"].unique()))
            st.markdown("###### 📌 点击标的弹出【同花顺】操盘 K 线买卖复盘：")
            p_cols = st.columns(min(len(all_unique_syms), 6))
            for i, sym in enumerate(all_unique_syms):
                col = p_cols[i % len(p_cols)]
                s_name = get_symbol_display_name(sym)
                if col.button(f"📊 {s_name} ({sym})", key=f"btn_sym_modal_{sym}", use_container_width=True):
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
        st.markdown("##### 📋 每日回测撮合原始明细")
        st.dataframe(df, use_container_width=True)
        csv_bytes = df.to_csv().encode('utf-8')
        st.download_button("📥 导出每日撮合明细 CSV", data=csv_bytes, file_name="backtest_report.csv", mime="text/csv")
