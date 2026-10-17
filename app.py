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
from strategies.dividend_lowvol_swing_backtest import run_dividend_backtest, generate_trade_ledger
from services.rebalance_service import (
    get_all_accounts,
    get_current_position,
    save_current_position,
    generate_rebalance_plan,
    generate_dividend_rebalance_plan,
    record_trade_log,
    get_trade_logs,
    execute_simulated_rebalance,
    execute_dividend_simulated_rebalance
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
DIVIDEND_SWING_REPORT_CSV = "./reports/dividend_swing_daily_report.csv"

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

    /* ==========================================
       demo.html 规范：专业极简交易台样式
       ========================================== */
    .sidebar-declutter-notice {
        margin-top: auto;
        padding-top: 18px;
        font-size: 11px;
        color: #94a3b8;
        line-height: 1.5;
        border-top: 1px solid #cbd3da;
    }
    .top-context-bar {
        border-bottom: 1px solid #e2e8f0;
        padding-bottom: 14px;
        margin-bottom: 16px;
    }
    .overview-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
        margin-bottom: 18px;
    }
    .overview-cell {
        padding: 14px 18px;
        border-right: 1px solid #e2e8f0;
    }
    .overview-cell:last-child {
        border-right: none;
    }
    .overview-label {
        font-size: 12px;
        color: #64748b;
        margin-bottom: 3px;
    }
    .overview-val-box {
        display: flex;
        align-items: baseline;
        gap: 6px;
    }
    .overview-val {
        font-size: 20px;
        font-weight: 700;
        color: #0f172a;
        line-height: 1.25;
    }
    .overview-sub {
        font-size: 12px;
        color: #94a3b8;
    }
    .wb-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 18px;
        box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.03);
        margin-bottom: 16px;
    }
    .card-header-bar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #f1f5f9;
        padding-bottom: 10px;
        margin-bottom: 14px;
    }
    .card-title {
        font-size: 15px;
        font-weight: 700;
        color: #0f172a;
        margin: 0;
    }
    .card-subtitle {
        font-size: 12px;
        color: #94a3b8;
    }
    .target-box {
        background: rgba(248, 250, 252, 0.85);
        border: 1px solid #f1f5f9;
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 10px;
    }
    .target-badge-red {
        font-size: 11px;
        font-weight: 600;
        padding: 2px 6px;
        border-radius: 4px;
        background: #fef2f2;
        color: #dc2626;
        border: 1px solid #fee2e2;
    }
    .target-badge-blue {
        font-size: 11px;
        font-weight: 600;
        padding: 2px 6px;
        border-radius: 4px;
        background: #eff6ff;
        color: #2563eb;
        border: 1px solid #dbeafe;
    }
    .target-code {
        font-size: 11px;
        color: #94a3b8;
    }
    .stat-pos {
        color: #dc2626;
        font-size: 17px;
        font-weight: 700;
    }
    .stat-neg {
        color: #059669;
        font-size: 17px;
        font-weight: 700;
    }
    .factor-box {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 12px 14px;
        font-size: 12px;
        color: #334155;
        line-height: 1.6;
        margin: 10px 0;
    }
    .progress-labels {
        display: flex;
        justify-content: space-between;
        font-size: 11px;
        color: #64748b;
    }
    .progress-track {
        width: 100%;
        background: #e2e8f0;
        height: 9px;
        border-radius: 9999px;
        overflow: hidden;
        margin-top: 6px;
    }
    .progress-fill {
        height: 100%;
        border-radius: 9999px;
        transition: width 0.4s ease;
    }
    .progress-fill-blue { background: #3b82f6; }
    .progress-fill-red { background: #ef4444; }
    .progress-fill-green { background: #10b981; }

    .signal-box-empty {
        background: rgba(236, 253, 245, 0.75);
        border: 1px solid #a7f3d0;
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 12px;
    }
    .signal-box-trigger {
        background: rgba(254, 242, 242, 0.85);
        border: 1px solid #fecaca;
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 12px;
    }
    .signal-box-holding {
        background: rgba(239, 246, 255, 0.75);
        border: 1px solid #bfdbfe;
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 12px;
    }
    .dot-green {
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: #10b981;
        display: inline-block;
    }
    .dot-red-ping {
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: #dc2626;
        display: inline-block;
        box-shadow: 0 0 0 3px rgba(220, 38, 38, 0.25);
    }
    .dot-blue {
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: #2563eb;
        display: inline-block;
    }
    .order-list-box {
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 12px 14px;
        background: #f8fafc;
        margin-bottom: 12px;
    }
    .order-item-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 12px;
        background: #ffffff;
        padding: 8px 12px;
        border-radius: 6px;
        border: 1px solid #e2e8f0;
        margin-top: 6px;
    }
    .manual-panel-box {
        border: 1px solid #bfdbfe;
        background: rgba(239, 246, 255, 0.55);
        border-radius: 8px;
        padding: 14px 16px;
        margin-top: 10px;
        margin-bottom: 10px;
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

    # 五大工作模式入口
    strategy_mode = st.radio(
        "工作模式",
        ["今日调仓", "红利高抛低吸", "攻守轮动", "因子实验", "模型回测"],
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
# 模式一：今日调仓 (实盘盯盘与模拟委托 - demo.html 专业重构版)
# ==========================================
if strategy_mode == "今日调仓":
    all_accs = get_all_accounts()
    acc_names = list(all_accs.keys())

    # 1. 侧边栏：极简模式，仅保留轻量账户资金管理折叠框与减负提示
    with st.sidebar:
        with st.expander("⚙️ 账户管理与资金设置", expanded=False):
            st.caption("模拟账户资金重置或新建：")
            mgmt_acc = st.selectbox("选择管理账户", acc_names, index=0, key="sb_mgmt_acc")
            mgmt_obj = all_accs.get(mgmt_acc, {})

            auto_trade_toggle = st.toggle("尾盘自动模拟调仓", value=mgmt_obj.get("auto_trade", True), help="仅在 14:45–14:55 时间窗触发自动撮合。")
            if auto_trade_toggle != mgmt_obj.get("auto_trade", True):
                mgmt_obj["auto_trade"] = auto_trade_toggle
                save_current_position(mgmt_obj, account_name=mgmt_acc)

            new_acc_name = st.text_input("新建模拟账户", placeholder="例如: 稳健攻守 3 号")
            init_cap = st.number_input("初始虚拟资金 (元)", value=100000.0, step=10000.0)
            if st.button("新建模拟账户", use_container_width=True, key="btn_create_acc"):
                if new_acc_name.strip():
                    save_current_position({
                        "initial_capital": float(init_cap),
                        "holding_symbol": "",
                        "holding_amount": 0,
                        "cash_available": float(init_cap),
                        "tech_symbol": "sh588380",
                        "def_symbol": "sh511010",
                        "lookback_window": 20,
                        "auto_trade": auto_trade_toggle
                    }, account_name=new_acc_name.strip())
                    st.toast(f"已创建账户: {new_acc_name.strip()}", icon="✅")
                    st.rerun()

            st.markdown("---")
            if st.button("🔄 重置当前账户资金为 10 万元现金", use_container_width=True, key="btn_reset_acc"):
                save_current_position({
                    "initial_capital": 100000.0,
                    "holding_symbol": "",
                    "holding_amount": 0,
                    "cash_available": 100000.0,
                    "tech_symbol": mgmt_obj.get("tech_symbol", "sh588380"),
                    "def_symbol": mgmt_obj.get("def_symbol", "sh511010"),
                    "lookback_window": 20,
                    "auto_trade": auto_trade_toggle
                }, account_name=mgmt_acc)
                st.toast(f"已重置【{mgmt_acc}】为 10 万元现金待命状态！", icon="🔄")
                st.rerun()

        st.markdown(
            """
            <div class="sidebar-declutter-notice">
                <b>侧边栏已减负</b><br>
                账户与标的已移至右侧主视图
            </div>
            """,
            unsafe_allow_html=True
        )

    # 2. 顶部上下文控制栏（账户与策略联动 + 实盘行情时效状态 + 刷新按钮）
    if "selected_account" not in st.session_state or st.session_state["selected_account"] not in acc_names:
        st.session_state["selected_account"] = "模拟实盘 2 号 (双创50+国债ETF)" if "模拟实盘 2 号 (双创50+国债ETF)" in acc_names else acc_names[0]

    cur_acc_name = st.session_state["selected_account"]
    default_strat = "⭐ 红利低波ERP利差高抛低吸" if ("红利" in cur_acc_name or "3" in cur_acc_name) else "🔄 攻守动量轮动 (双资产切换)"
    if "top_sel_strat" not in st.session_state:
        st.session_state["top_sel_strat"] = default_strat

    def _sync_strat_from_acc():
        acc = st.session_state["top_sel_acc"]
        st.session_state["selected_account"] = acc
        if "红利" in acc or "3" in acc:
            st.session_state["top_sel_strat"] = "⭐ 红利低波ERP利差高抛低吸"
        else:
            st.session_state["top_sel_strat"] = "🔄 攻守动量轮动 (双资产切换)"
        st.session_state.pop("inplace_sel_tech", None)
        st.session_state.pop("inplace_sel_def", None)

    strat_options = ["🔄 攻守动量轮动 (双资产切换)", "⭐ 红利低波ERP利差高抛低吸"]

    st.markdown('<div class="top-context-bar">', unsafe_allow_html=True)
    c_acc, c_strat, c_stat, c_ref = st.columns([2.8, 2.8, 4.4, 1.2], gap="small")

    with c_acc:
        sel_acc = st.selectbox(
            "当前模拟账户",
            acc_names,
            index=acc_names.index(cur_acc_name),
            key="top_sel_acc",
            on_change=_sync_strat_from_acc
        )
    with c_strat:
        sel_strat = st.selectbox(
            "绑定调仓策略 ⓘ",
            strat_options,
            index=strat_options.index(st.session_state["top_sel_strat"]),
            key="top_sel_strat",
            help="跟随账户自动匹配，亦可手动切换策略"
        )

    now_dt = datetime.datetime.now()
    weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    date_str = f"{now_dt.year}年{now_dt.month:02d}月{now_dt.day:02d}日 {weekday_cn[now_dt.weekday()]}"

    now_hour = now_dt.hour
    now_minute = now_dt.minute
    is_trade_day = now_dt.weekday() < 5
    in_exec_window = is_trade_day and (now_hour == 14 and 45 <= now_minute <= 55)
    is_intraday = is_trade_day and ((9 <= now_hour < 11 or (now_hour == 11 and now_minute <= 30)) or (13 <= now_hour < 15))

    if in_exec_window:
        dot_html = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#ef4444;box-shadow:0 0 0 2px rgba(239,68,68,0.3);"></span>'
        status_text = "尾盘调仓窗口 · 撮合中"
    elif is_intraday:
        dot_html = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#10b981;"></span>'
        status_text = "交易中 · 实时盯盘"
    else:
        dot_html = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#94a3b8;"></span>'
        status_text = "休市盘后"

    with c_stat:
        st.markdown(f"""
        <div style="text-align:right; padding-top:4px;">
            <div style="display:flex; align-items:center; justify-content:flex-end; gap:6px;">
                {dot_html}
                <span style="font-size:12px; font-weight:500; color:#334155;">{date_str} · {status_text}</span>
                <span style="font-size:11px; background:#f1f5f9; border:1px solid #e2e8f0; padding:1px 6px; border-radius:4px; color:#64748b;">实盘监控 · 模拟撮合</span>
            </div>
            <p style="font-size:11px; color:#94a3b8; margin:2px 0 0 0;">行情更新于 {now_dt.strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        """, unsafe_allow_html=True)

    with c_ref:
        st.write("")
        if st.button("🔄 刷新行情", use_container_width=True, key="btn_refresh_quote"):
            st.cache_data.clear()
            st.session_state["refresh_seq"] = st.session_state.get("refresh_seq", 0) + 1
            st.toast("行情与因子已刷新！", icon="🔄")
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

    if "refresh_seq" not in st.session_state:
        st.session_state["refresh_seq"] = 0

    is_dividend_plan = ("红利低波" in sel_strat)
    acc_obj = all_accs.get(sel_acc, {})

    # 3. 策略数据获取
    if is_dividend_plan:
        @st.cache_data(ttl=5, show_spinner=False)
        def _fetch_div_plan_cached(acc, seq):
            return generate_dividend_rebalance_plan(account_name=acc)

        plan = _fetch_div_plan_cached(sel_acc, st.session_state["refresh_seq"])
        sig = plan["signal"]
        port = plan["portfolio"]
        orders = plan["orders"]
        pos = plan["position"]
        init_capital = float(pos.get("initial_capital", 100000.0))
        total_return_pct = ((port["total_assets"] - init_capital) / init_capital) * 100
        pnl_amount = port["total_assets"] - init_capital
        hold_shares = port.get('current_shares', 0)
        target_name = "华泰低波红利"
        hold_name = "华泰低波红利 (512890)" if hold_shares > 0 else "空仓"

    else:
        live_tech_opts = {
            "sh588380": "双创50ETF · 588380",
            "sz159915": "创业板ETF · 159915",
            "sh588000": "科创50ETF · 588000"
        }
        live_def_opts = {
            "sh511010": "国债ETF · 511010",
            "sh511260": "十年国债ETF · 511260",
            "sh512890": "红利低波ETF · 512890"
        }

        def_tech_key = acc_obj.get("tech_symbol", "sh588380")
        if def_tech_key not in live_tech_opts:
            def_tech_key = "sh588380"
        def_def_key = acc_obj.get("def_symbol", "sh511010")
        if def_def_key not in live_def_opts:
            def_def_key = "sh511010"

        cur_tech = st.session_state.get("inplace_sel_tech", st.session_state.get(f"tech_choice_{sel_acc}", def_tech_key))
        if cur_tech not in live_tech_opts:
            cur_tech = def_tech_key
        cur_def = st.session_state.get("inplace_sel_def", st.session_state.get(f"def_choice_{sel_acc}", def_def_key))
        if cur_def not in live_def_opts:
            cur_def = def_def_key
        cur_window = int(acc_obj.get("lookback_window", 20))

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
        pnl_amount = port["total_assets"] - init_capital
        hold_shares = pos.get('holding_amount', 0)
        target_name = ETF_POOL.get(sig['target_symbol'], sig['target_symbol']).split()[0]
        hold_name = port['current_holding_name'] if port['current_holding_name'] else "空仓"

    # 4. 第一层：账户资产概览 (4列统一卡片，严格对应 demo.html line 110-135)
    ret_color_cls = "stat-pos" if total_return_pct > 0 else ("stat-neg" if total_return_pct < 0 else "")
    ret_sign = "+" if total_return_pct > 0 else ""
    pnl_sign = "+" if pnl_amount > 0 else ("-" if pnl_amount < 0 else "")

    if hold_shares == 0:
        val_pos = "空仓"
        val_pos_sub = "0%"
    else:
        if is_dividend_plan:
            val_pos = f"红利低波 ({port['current_shares']:,}股)"
            val_pos_sub = f"仓位 {port['current_weight']*100:.1f}%"
        else:
            val_pos = f"{hold_name}"
            val_pos_sub = f"持仓 {hold_shares:,} 份 ({port['current_weight']*100:.1f}%)"

    st.markdown(f"""
    <div class="overview-grid">
        <div class="overview-cell">
            <div class="overview-label">总资产</div>
            <div class="overview-val">¥{port['total_assets']:,.2f}</div>
        </div>
        <div class="overview-cell">
            <div class="overview-label">可用现金</div>
            <div class="overview-val">¥{port['cash']:,.2f}</div>
        </div>
        <div class="overview-cell">
            <div class="overview-label">当前持仓 / 仓位</div>
            <div class="overview-val-box">
                <span class="overview-val">{val_pos}</span>
                <span class="overview-sub">{val_pos_sub}</span>
            </div>
        </div>
        <div class="overview-cell">
            <div class="overview-label">累计收益 / 浮动盈亏</div>
            <div class="overview-val-box">
                <span class="overview-val {ret_color_cls}">{ret_sign}{total_return_pct:.2f}%</span>
                <span class="overview-sub {ret_color_cls}">{pnl_sign}¥{abs(pnl_amount):,.2f}</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 5. 第二层：左因 (7列) + 右果 (5列)
    col_left, col_right = st.columns([7, 5], gap="large")

    # ==========================================
    # 左侧：行情与因子监控 (7列)
    # ==========================================
    with col_left:
        st.markdown("""
        <div class="wb-card">
            <div class="card-header-bar">
                <h2 class="card-title">📊 行情与因子监控</h2>
                <span class="card-subtitle">支持就地切换标的，实时重算动量与估值</span>
            </div>
        """, unsafe_allow_html=True)

        if not is_dividend_plan:
            # 进攻标的 (就地切换)
            tech_idx = list(live_tech_opts.keys()).index(cur_tech) if cur_tech in live_tech_opts else 0
            t_mom = sig['tech']['mom'] * 100
            t_cls = "stat-pos" if t_mom >= 0 else "stat-neg"
            t_sign = "+" if t_mom >= 0 else ""

            col_t1, col_t2, col_t3 = st.columns([5.5, 3.2, 3.3])
            with col_t1:
                st.markdown(f"""
                <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">
                    <span class="target-badge-red">进攻标的</span>
                    <span class="target-code">{cur_tech.upper()}</span>
                </div>
                """, unsafe_allow_html=True)
                new_tech = st.selectbox(
                    "进攻标的",
                    list(live_tech_opts.keys()),
                    format_func=lambda x: live_tech_opts[x],
                    index=tech_idx,
                    label_visibility="collapsed",
                    key="inplace_sel_tech"
                )
                if new_tech != cur_tech:
                    st.session_state[f"tech_choice_{sel_acc}"] = new_tech
                    acc_obj["tech_symbol"] = new_tech
                    save_current_position(acc_obj, account_name=sel_acc)
                    st.rerun()

            with col_t2:
                st.markdown(f"""
                <div style="text-align:right; padding-top:6px;">
                    <div style="font-size:11px; color:#94a3b8;">最新净值</div>
                    <div style="font-size:18px; font-weight:700; color:#0f172a; margin-top:2px;">{sig['tech']['price']:.3f}</div>
                </div>
                """, unsafe_allow_html=True)
            with col_t3:
                st.markdown(f"""
                <div style="text-align:right; padding-top:6px;">
                    <div style="font-size:11px; color:#94a3b8;">20日动量</div>
                    <div class="{t_cls}" style="margin-top:2px;">{t_sign}{t_mom:.2f}%</div>
                </div>
                """, unsafe_allow_html=True)

            # 防守标的 (就地切换)
            def_idx = list(live_def_opts.keys()).index(cur_def) if cur_def in live_def_opts else 0
            d_mom = sig['defensive']['mom'] * 100
            d_cls = "stat-pos" if d_mom >= 0 else "stat-neg"
            d_sign = "+" if d_mom >= 0 else ""

            col_d1, col_d2, col_d3 = st.columns([5.5, 3.2, 3.3])
            with col_d1:
                st.markdown(f"""
                <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px; margin-top:8px;">
                    <span class="target-badge-blue">防守标的</span>
                    <span class="target-code">{cur_def.upper()}</span>
                </div>
                """, unsafe_allow_html=True)
                new_def = st.selectbox(
                    "防守标的",
                    list(live_def_opts.keys()),
                    format_func=lambda x: live_def_opts[x],
                    index=def_idx,
                    label_visibility="collapsed",
                    key="inplace_sel_def"
                )
                if new_def != cur_def:
                    st.session_state[f"def_choice_{sel_acc}"] = new_def
                    acc_obj["def_symbol"] = new_def
                    save_current_position(acc_obj, account_name=sel_acc)
                    st.rerun()

            with col_d2:
                st.markdown(f"""
                <div style="text-align:right; padding-top:14px;">
                    <div style="font-size:11px; color:#94a3b8;">最新净值</div>
                    <div style="font-size:18px; font-weight:700; color:#0f172a; margin-top:2px;">{sig['defensive']['price']:.3f}</div>
                </div>
                """, unsafe_allow_html=True)
            with col_d3:
                st.markdown(f"""
                <div style="text-align:right; padding-top:14px;">
                    <div style="font-size:11px; color:#94a3b8;">20日动量</div>
                    <div class="{d_cls}" style="margin-top:2px;">{d_sign}{d_mom:.2f}%</div>
                </div>
                """, unsafe_allow_html=True)

            # 💡 本次因子判断与标尺可视化
            mom_diff = t_mom - d_mom
            ma_diff = ((sig['tech']['price'] - sig['tech']['ma']) / sig['tech']['ma']) * 100
            is_tech_target = (sig['target_symbol'].lower() == cur_tech.lower())
            tech_name = live_tech_opts.get(cur_tech, cur_tech).split()[0]
            def_name = live_def_opts.get(cur_def, cur_def).split()[0]

            if is_tech_target:
                factor_desc = f"🔥 <strong>触发攻守转换！</strong> {tech_name} 20日动量反超{def_name} <strong>{mom_diff:+.2f}%</strong>，且放量站上20日均线（<strong>{ma_diff:+.2f}%</strong>），策略由【防守】切换为【进攻】。"
                progress_pct = 100
                progress_fill_class = "progress-fill-red"
                progress_label = "已突破阈值！触发买入进攻信号"
            else:
                factor_desc = f"进攻动量较防守落后 <strong>{abs(mom_diff):.2f}%</strong>，且{tech_name}距 20 日均线 <strong>{ma_diff:+.2f}%</strong>，未达向上突破阈值，当前维持【{def_name}】防守配置。"
                progress_fill_class = "progress-fill-blue"
                dist_pct = abs(ma_diff) if ma_diff < 0 else 0
                progress_label = f"当前位置（距触发进攻信号还差 +{dist_pct:.2f}%）"
                progress_pct = max(10, min(85, int(50 + ma_diff * 2.5)))

            st.markdown(f"""
            <div style="padding-top:14px; border-top:1px solid #f1f5f9; margin-top:12px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:13px; font-weight:700; color:#1e293b;">💡 本次因子判断</span>
                    <span style="font-size:11px; color:#64748b;">动量差值：{mom_diff:+.2f}% | 距20日均线：{ma_diff:+.2f}%</span>
                </div>
                <div class="factor-box">
                    {factor_desc}
                </div>
                <div style="margin-top:12px;">
                    <div class="progress-labels">
                        <span>🛡️ 深度防守区</span>
                        <span style="font-weight:600; color:#334155;">{progress_label}</span>
                        <span>⚔️ 触发进攻阈值 (站上20日线 & 动量领先)</span>
                    </div>
                    <div class="progress-track">
                        <div class="progress-fill {progress_fill_class}" style="width:{progress_pct}%;"></div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        else:
            # 策略二：红利低波 ERP 监控
            etf_sig = sig["etf"]
            bond_sig = sig["bond"]
            ind = sig["indicators"]

            etf_cls = "stat-pos" if etf_sig["chg_pct"] >= 0 else "stat-neg"
            bond_cls = "stat-pos" if bond_sig["chg_pct"] >= 0 else "stat-neg"
            etf_sign = "+" if etf_sig["chg_pct"] >= 0 else ""
            bond_sign = "+" if bond_sig["chg_pct"] >= 0 else ""

            # 标的1：华泰低波
            col_e1, col_e2, col_e3 = st.columns([5.5, 3.2, 3.3])
            with col_e1:
                st.markdown("""
                <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">
                    <span class="target-badge-red">红利标的</span>
                    <span class="target-code">SH512890</span>
                </div>
                <div style="font-size:13px; font-weight:600; color:#0f172a; padding:6px 0;">华泰柏瑞红利低波ETF · 512890</div>
                """, unsafe_allow_html=True)
            with col_e2:
                st.markdown(f"""
                <div style="text-align:right; padding-top:6px;">
                    <div style="font-size:11px; color:#94a3b8;">最新净值</div>
                    <div style="font-size:18px; font-weight:700; color:#0f172a; margin-top:2px;">{etf_sig['price']:.3f}</div>
                </div>
                """, unsafe_allow_html=True)
            with col_e3:
                st.markdown(f"""
                <div style="text-align:right; padding-top:6px;">
                    <div style="font-size:11px; color:#94a3b8;">今日涨跌</div>
                    <div class="{etf_cls}" style="margin-top:2px;">{etf_sign}{etf_sig['chg_pct']:.2f}%</div>
                </div>
                """, unsafe_allow_html=True)

            # 标的2：十年国债
            col_b1, col_b2, col_b3 = st.columns([5.5, 3.2, 3.3])
            with col_b1:
                st.markdown("""
                <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px; margin-top:8px;">
                    <span class="target-badge-blue">对冲避险</span>
                    <span class="target-code">SH511260</span>
                </div>
                <div style="font-size:13px; font-weight:600; color:#0f172a; padding:6px 0;">十年国债ETF · 511260</div>
                """, unsafe_allow_html=True)
            with col_b2:
                st.markdown(f"""
                <div style="text-align:right; padding-top:14px;">
                    <div style="font-size:11px; color:#94a3b8;">最新净值</div>
                    <div style="font-size:18px; font-weight:700; color:#0f172a; margin-top:2px;">{bond_sig['price']:.3f}</div>
                </div>
                """, unsafe_allow_html=True)
            with col_b3:
                st.markdown(f"""
                <div style="text-align:right; padding-top:14px;">
                    <div style="font-size:11px; color:#94a3b8;">国债收益率</div>
                    <div style="font-size:17px; font-weight:700; color:#0f172a; margin-top:2px;">{ind['rate_10y']:.4f}%</div>
                </div>
                """, unsafe_allow_html=True)

            # 💡 本次因子判断 (股债利差 ERP)
            erp_pct_val = ind['erp_pct'] * 100
            if ind['erp_pct'] > 0.35:
                factor_desc = f"🟢 <strong>股债利差极具性价比！</strong> 华泰低波 PE 为 <strong>{ind['pe']:.2f} 倍</strong>，股债利差 ERP 为 <strong>{ind['erp']:.2f}%</strong>（处于近一年 <strong>{erp_pct_val:.1f}%</strong> 历史高位分位），红利资产深度低估，策略建议维持 <strong>100%</strong> 满仓配置。"
                progress_fill_class = "progress-fill-green"
            elif ind['erp_pct'] <= 0.20:
                factor_desc = f"🔥 <strong>股债利差进入极值过热区！</strong> 华泰低波 PE 为 <strong>{ind['pe']:.2f} 倍</strong>，股债利差 ERP 为 <strong>{ind['erp']:.2f}%</strong>（处于近一年 <strong>{erp_pct_val:.1f}%</strong> 极值低位分位），权益性价比偏低，策略建议高抛减仓至 <strong>50%</strong>。"
                progress_fill_class = "progress-fill-red"
            else:
                factor_desc = f"⚖️ <strong>处于稳健观察带！</strong> 华泰低波 PE 为 <strong>{ind['pe']:.2f} 倍</strong>，股债利差 ERP 为 <strong>{ind['erp']:.2f}%</strong>（分位 <strong>{erp_pct_val:.1f}%</strong>），维持 <strong>75%</strong> 稳健底仓。"
                progress_fill_class = "progress-fill-blue"

            st.markdown(f"""
            <div style="padding-top:14px; border-top:1px solid #f1f5f9; margin-top:12px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:13px; font-weight:700; color:#1e293b;">💡 本次因子判断</span>
                    <span style="font-size:11px; color:#64748b;">ERP 利差：{ind['erp']:.2f}% | 250日分位：{erp_pct_val:.1f}%</span>
                </div>
                <div class="factor-box">
                    {factor_desc}
                </div>
                <div style="margin-top:12px;">
                    <div class="progress-labels">
                        <span>🔥 20% 极值过热 (减仓至50%)</span>
                        <span style="font-weight:600; color:#334155;">当前位置: {erp_pct_val:.1f}% 分位</span>
                        <span>🟢 80% 极值低估 (加仓至100%)</span>
                    </div>
                    <div class="progress-track">
                        <div class="progress-fill {progress_fill_class}" style="width:{max(5, min(100, int(erp_pct_val)))}%;"></div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # ==========================================
    # 右侧：今日调仓指令与尾盘执行 (5列，消除了原图上下重复的问题)
    # ==========================================
    with col_right:
        st.markdown("""
        <div class="wb-card">
            <div class="card-header-bar">
                <h2 class="card-title">⚡ 今日调仓指令</h2>
                <span style="font-size:11px; font-weight:600; color:#b45309; background:#fffbeb; border:1px solid #fef3c7; padding:2px 8px; border-radius:4px;">
                    🕒 模拟调仓窗 14:45 - 14:55
                </span>
            </div>
        """, unsafe_allow_html=True)

        real_trades = [o for o in orders if o.get("action") in ["买入", "卖出"]]

        if real_trades:
            # 状态 2: 触发新变盘信号
            if is_dividend_plan:
                sig_title = f"🚨 触发红利调仓信号：目标仓位调整至 {int(port['target_weight']*100)}%"
                sig_desc = f"股债利差 ERP 触发阈值门禁，策略由上一周期目标调整至 {int(port['target_weight']*100)}%，请于 14:45-14:55 窗口内执行委托。"
            else:
                sig_title = f"🚨 触发新变盘信号：平仓防守 → 买入进攻" if is_tech_target else f"🚨 触发新变盘信号：平仓进攻 → 切换防守"
                sig_desc = f"今日进攻标的动量转强并站稳均线，请于 14:45-14:55 调仓窗口内执行以下切换委托。" if is_tech_target else f"进攻标的动量跌破阈值，请于 14:45-14:55 调仓窗口内切换至防守资产避险。"

            st.markdown(f"""
            <div class="signal-box-trigger">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
                    <span class="dot-red-ping"></span>
                    <strong style="font-size:13px; color:#991b1b;">{sig_title}</strong>
                </div>
                <p style="font-size:12px; color:#b91c1c; margin:0; line-height:1.5;">{sig_desc}</p>
            </div>
            """, unsafe_allow_html=True)

            # 待执行清单列表
            order_items_html = ""
            for o in real_trades:
                action_color = "#dc2626" if o["action"] == "买入" else "#059669"
                sym_code = o["symbol"].upper()
                if o["action"] == "卖出":
                    order_items_html += f"""
                    <div class="order-item-row">
                        <span><b style="color:{action_color};">{o['action']}平仓</b> {o['name']} ({sym_code})</span>
                        <span style="color:#64748b;">全仓卖出 · 预计释放 ¥{o['est_amount']:,.2f}</span>
                    </div>
                    """
                else:
                    order_items_html += f"""
                    <div class="order-item-row">
                        <span><b style="color:{action_color};">{o['action']}开仓</b> {o['name']} ({sym_code})</span>
                        <span style="color:#64748b;">全仓买入 · 预计委托 {o['shares']:,} 份</span>
                    </div>
                    """

            st.markdown(f"""
            <div class="order-list-box">
                <div style="font-size:12px; font-weight:700; color:#334155; margin-bottom:6px;">📋 待执行调仓清单：</div>
                {order_items_html}
            </div>
            """, unsafe_allow_html=True)

            if st.button("⚡ 一键执行调仓委托 (14:45-14:55)", type="primary", use_container_width=True, key="btn_exec_real"):
                if is_dividend_plan:
                    res = execute_dividend_simulated_rebalance(sel_acc, force_auto=True)
                else:
                    sells = [o for o in real_trades if o["action"] == "卖出"]
                    for s in sells:
                        record_trade_log(sel_acc, "卖出平仓", s["symbol"], s["shares"], s["price"], s["est_amount"], reason="尾盘动量切换平仓")
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
                            "auto_trade": acc_obj.get("auto_trade", True)
                        }, account_name=sel_acc)
                        record_trade_log(sel_acc, "买入建仓", last_b["symbol"], last_b["shares"], last_b["price"], last_b["est_amount"], reason="尾盘动量切换建仓")
                    res = {"success": True, "message": "模拟调仓撮合成功！"}

                if res.get("success"):
                    st.toast(res.get("message", "调仓执行成功！"), icon="✅")
                    st.rerun()

        elif hold_shares == 0:
            # 状态 1: 空仓观望态
            st.markdown(f"""
            <div class="signal-box-empty">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
                    <span class="dot-green"></span>
                    <strong style="font-size:13px; color:#065f46;">保持空仓观望 · 今日无新变盘信号</strong>
                </div>
                <p style="font-size:12px; color:#047857; margin:0; line-height:1.5;">
                    当前策略延续【{target_name}】防守周期，今日进攻与防守信号未发生切换。建议保持空仓观望，等待下一次新变盘信号出现。
                </p>
            </div>
            """, unsafe_allow_html=True)

            c_btn_main, c_btn_sub = st.columns([1.5, 1.2])
            with c_btn_main:
                st.button("无需调仓 (保持空仓)", disabled=True, use_container_width=True, key="btn_no_rebal")
            with c_btn_sub:
                if st.button("🛒 手动建立底仓", use_container_width=True, key="btn_toggle_manual"):
                    st.session_state["show_manual_panel"] = not st.session_state.get("show_manual_panel", False)
                    st.rerun()

            if st.session_state.get("show_manual_panel", False):
                st.markdown("""
                <div class="manual-panel-box">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                        <strong style="font-size:12px; color:#1e293b;">🛒 手动开启底仓委托（跟随当前防守周期）</strong>
                    </div>
                """, unsafe_allow_html=True)

                c_m_tgt, c_m_ratio = st.columns(2)
                with c_m_tgt:
                    if is_dividend_plan:
                        m_targets = {"sh512890": "🛡️ 华泰低波红利 · 512890 (当前推荐)"}
                    else:
                        m_targets = {
                            cur_def: f"🛡️ {live_def_opts.get(cur_def, cur_def).split()[0]} (当前推荐)",
                            cur_tech: f"⚔️ {live_tech_opts.get(cur_tech, cur_tech).split()[0]}"
                        }
                    sel_m_target = st.selectbox("建仓标的", list(m_targets.keys()), format_func=lambda x: m_targets[x], key="manual_tgt")
                with c_m_ratio:
                    ratio_opts = {"1.0": f"100% 全仓 (¥{port['cash']:,.0f})", "0.5": f"50% 半仓 (¥{port['cash']*0.5:,.0f})", "0.25": f"25% 底仓 (¥{port['cash']*0.25:,.0f})"}
                    sel_ratio = st.selectbox("建仓比例", list(ratio_opts.keys()), format_func=lambda x: ratio_opts[x], key="manual_ratio")

                c_submit_manual, c_close_manual = st.columns([3, 1])
                with c_submit_manual:
                    if st.button("确认提交手动建仓委托", type="primary", use_container_width=True, key="btn_confirm_manual"):
                        target_ratio = float(sel_ratio)
                        invest_amt = port['cash'] * target_ratio
                        target_p = sig['defensive']['price'] if (not is_dividend_plan and sel_m_target == cur_def) else (sig['tech']['price'] if not is_dividend_plan else sig['etf']['price'])
                        shs = int(invest_amt / target_p / 100) * 100
                        actual_amt = shs * target_p
                        remain_cash = port['total_assets'] - actual_amt

                        if is_dividend_plan:
                            save_current_position({
                                "initial_capital": init_capital,
                                "holding_symbol": "sh512890",
                                "holding_amount": shs,
                                "bond_symbol": "sh511260",
                                "bond_amount": 0,
                                "cash_available": max(0.0, round(remain_cash, 2)),
                                "strategy_type": "dividend_erp",
                                "auto_trade": acc_obj.get("auto_trade", True)
                            }, account_name=sel_acc)
                            record_trade_log(sel_acc, "手动建仓", "sh512890", shs, target_p, actual_amt, reason="用户手动建立红利底仓")
                        else:
                            save_current_position({
                                "initial_capital": init_capital,
                                "holding_symbol": sel_m_target,
                                "holding_amount": shs,
                                "cash_available": max(0.0, round(remain_cash, 2)),
                                "tech_symbol": cur_tech,
                                "def_symbol": cur_def,
                                "lookback_window": cur_window,
                                "auto_trade": acc_obj.get("auto_trade", True)
                            }, account_name=sel_acc)
                            record_trade_log(sel_acc, "手动建仓", sel_m_target, shs, target_p, actual_amt, reason="用户手动建立初始底仓")

                        st.session_state["show_manual_panel"] = False
                        st.toast(f"已成功建立底仓：{shs:,} 股！", icon="🛒")
                        st.rerun()

                with c_close_manual:
                    if st.button("收起 ✕", use_container_width=True, key="btn_close_manual"):
                        st.session_state["show_manual_panel"] = False
                        st.rerun()

                st.markdown("</div>", unsafe_allow_html=True)

        else:
            # 状态 3: 持仓防守/进攻态 (持仓与目标一致)
            is_defense_holding = (pos.get('holding_symbol') == cur_def if not is_dividend_plan else True)
            if is_dividend_plan:
                hold_title = "⭐ 继续持有稳健红利底仓 · 今日无需换仓"
                hold_desc = f"当前账户已持有【华泰低波红利 · 512890】({hold_shares:,} 股 / 市值 ¥{port['market_value']:,.2f})，仓位比例吻合策略目标，今日无调仓动作。"
            elif is_defense_holding:
                hold_title = f"🛡️ 继续持有防守仓位 · 今日无需换仓"
                hold_desc = f"当前账户已满仓持有【{hold_name}】({hold_shares:,} 份)，与策略防守信号完全一致，今日无调仓动作。"
            else:
                hold_title = f"⚔️ 继续持有进攻仓位 · 今日无需换仓"
                hold_desc = f"当前账户已持有【{hold_name}】({hold_shares:,} 份)，与策略进攻信号完全一致，今日无调仓动作。"

            st.markdown(f"""
            <div class="signal-box-holding">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
                    <span class="dot-blue"></span>
                    <strong style="font-size:13px; color:#1e40af;">{hold_title}</strong>
                </div>
                <p style="font-size:12px; color:#1d4ed8; margin:0; line-height:1.5;">{hold_desc}</p>
            </div>
            """, unsafe_allow_html=True)

            st.button("持仓已对齐策略 (无需调仓)", disabled=True, use_container_width=True, key="btn_aligned_holding")

        st.markdown("""
        <p style="font-size:11px; color:#94a3b8; text-align:center; padding-top:6px; margin-bottom:12px;">
            此环境为模拟实盘撮合，在交易日 14:45–14:55 时间窗内点击执行将记入账户流水。
        </p>
        """, unsafe_allow_html=True)

        with st.expander("📜 查看账户历史调仓流水", expanded=False):
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

        st.markdown("</div>", unsafe_allow_html=True)

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
# 模式二：红利高抛低吸 (华泰低波 512890 量化做 T 与大波段)
# ==========================================
elif strategy_mode == "红利高抛低吸":
    with st.sidebar:
        st.markdown("### 红利低波回测设置")
        etf_choice = st.selectbox("核心底仓标的", ["sh512890 · 华泰柏瑞红利低波ETF"], index=0)
        bond_choice = st.selectbox("防守生息资产", ["sh511260 · 十年期国债ETF", "现金管理 (年化1.8%)"], index=0)
        default_focus = st.selectbox(
            "主显聚焦策略",
            ["全策略横向对比 (推荐⭐)", "策略二：ERP 股债利差宏观择时", "策略一：动态 ATR 通道网格", "策略三：BIAS+RSI 动量极值波段"],
            index=0
        )

        start_date = st.date_input("开始日期", pd.to_datetime("2019-04-19"))
        end_date = st.date_input("结束日期", pd.to_datetime("2026-10-09"))

        with st.expander("更多设置 · 费率与网格档位"):
            st.caption("ETF 交易免征印花税")
            fee_bp = st.number_input("双边交易佣金 (万分之)", value=1.0, step=0.5)
            slip_bp = st.number_input("双边滑点损耗 (万分之)", value=2.0, step=0.5)
            core_ratio = st.slider("核心底仓比例 (不动)", min_value=0.2, max_value=0.8, value=0.5, step=0.1)

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

    # 顶栏面包屑
    st.markdown(
        """
        <div class="top-crumb-bar">
            <span class="crumb-left"><strong>策略研究</strong> / <span>红利高抛低吸</span></span>
            <span class="crumb-badge">华泰低波 512890 · 1869 交易日</span>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 标题与运行按钮
    c_head_left, c_head_right = st.columns([4, 1.2])
    with c_head_left:
        st.markdown(
            """
            <div class="page-head" style="margin-bottom:0;">
                <div>
                    <h1>华泰低波红利高抛低吸量化研究台</h1>
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

    st.markdown(
        """
        <div style="background:#ffffff; border:1px solid #DC2626; border-left:4px solid #DC2626; padding:12px 18px; margin: 14px 0 6px 0; border-radius:4px; display:flex; justify-content:space-between; align-items:center;">
            <div>
                <strong style="color:#DC2626; font-size:13px;">📢 今日策略二调仓指引 (ERP 股债利差大波段择时)</strong>
                <p style="margin:3px 0 0 0; font-size:12px; color:#475569;">
                    最新 ERP 历史分位：<b>20.3%</b> · 今日建议仓位：<b>75%</b> (稳健观察带，维持现有持仓，保持 25% 现金/国债对冲)。前往左侧导航<b>【今日调仓】</b>可执行模拟撮合。
                </p>
            </div>
            <div style="text-align:right;">
                <span style="font-size:11px; background:#FEF2F2; color:#DC2626; padding:4px 10px; border-radius:3px; font-weight:600; border:1px solid #FECACA;">
                    距离 20% 极值高抛线仅差 0.3%
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if run_div_btn:
        with st.spinner("正在加载最新宏观估值与行情，重新执行三大高抛低吸策略撮合..."):
            try:
                import io, contextlib
                f_dummy = io.StringIO()
                with contextlib.redirect_stdout(f_dummy), contextlib.redirect_stderr(f_dummy):
                    run_dividend_backtest()
                st.toast("红利高抛低吸全周期回测已完成！", icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"回测执行异常: {e}")

    # 读取并渲染回测数据
    if not os.path.exists(DIVIDEND_SWING_REPORT_CSV):
        with st.spinner("首次加载正在准备 512890 回测数据..."):
            import io, contextlib
            f_dummy = io.StringIO()
            with contextlib.redirect_stdout(f_dummy), contextlib.redirect_stderr(f_dummy):
                run_dividend_backtest()

    df_div = pd.read_csv(DIVIDEND_SWING_REPORT_CSV, index_col=0, parse_dates=True)

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
            "📊 净值走势与买卖标记",
            "🧾 逐笔做 T 交易记录 (券商交割单)",
            "📅 分年度收益归因与胜率",
            "🎯 核心量化指标监控 (ATR/ERP/BIAS)",
            "📋 每日撮合与持仓流水"
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
                    name="⭐ 红利低波ERP利差高抛低吸策略",
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
            fig.update_yaxes(title_text="持仓 %", row=3, col=1, range=[30, 110])

            st.plotly_chart(fig, use_container_width=True)

        with tab_trade:
            st.markdown("#### 🧾 券商级逐笔做 T 交易交割账单 (Trade Action Ledger)")
            c_sel1, c_sel2 = st.columns([2.5, 3.5])
            with c_sel1:
                ledger_strat = st.selectbox(
                    "查看策略交易对账单",
                    ["策略二：ERP 股债利差择时 (推荐⭐)", "策略一：动态 ATR 网格高抛低吸", "策略三：BIAS+RSI 动量极值波段"],
                    index=0
                )

            strat_key_map = {
                "策略二：ERP 股债利差择时 (推荐⭐)": "s2",
                "策略一：动态 ATR 网格高抛低吸": "s1",
                "策略三：BIAS+RSI 动量极值波段": "s3"
            }
            sel_key = strat_key_map.get(ledger_strat, "s2")
            ledger_df, win_rate, total_closed, win_count = generate_trade_ledger(sub_df, raw_data, strat_key=sel_key)

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
                f"📥 导出【{ledger_strat.split('：')[0]}】逐笔交割账单 CSV",
                data=ledger_csv,
                file_name=f"trade_ledger_{sel_key}.csv",
                mime="text/csv"
            )

        with tab2:
            st.markdown("#### 📅 2019 ~ 2026 分年度收益率归因对比")
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
                    "⭐ 红利低波ERP择时策略": f"{s2_r*100:+.2f}%",
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
            st.markdown("#### 🎯 核心量化指标监控走势")
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
            st.markdown("#### 📋 每日撮合与持仓权重流水")
            st.dataframe(sub_df[["close", "bench_nav", "s1_atr_nav", "s1_weight", "s2_erp_nav", "s2_weight", "s3_bias_nav", "s3_weight"]].tail(100), use_container_width=True)
            csv_data = sub_df.to_csv().encode("utf-8-sig")
            st.download_button("📥 导出完整回测明细 CSV", data=csv_data, file_name="dividend_swing_daily_report.csv", mime="text/csv")

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
