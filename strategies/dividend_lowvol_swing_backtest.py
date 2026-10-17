#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
华泰柏瑞红利低波 ETF (512890) 高抛低吸量化策略回测引擎与交易交割单生成器
回测周期: 2019-04 至 2026-10 (全历史 1800+ 交易日)

涵盖策略:
1. 基准: 华泰低波红利 (512890) 买入持有 (Buy & Hold)
2. 策略一: 动态 ATR 通道网格高抛低吸 (Dynamic ATR Channel Grid)
3. 策略二: 股债性价比 / 股债利差 (ERP) 宏观大波段高抛低吸 (Macro ERP Spread Swing)
4. 策略三: BIAS 乖离率 + RSI 动量极值波段高抛低吸 (BIAS & RSI Extreme Reversion)
"""

import os
import sys
from pathlib import Path

# 添加工程根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 标的与数据配置
ETF_SYMBOL = "sh512890"        # 华泰柏瑞中证红利低波动 ETF
BOND_SYMBOL = "sh511260"       # 十年期国债 ETF (用于对冲/高抛后闲置资金生息配置)
CACHE_DIR = Path("./data")
REPORT_DIR = Path("./reports")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

def safe_print(*args, **kwargs):
    """安全打印函数，防范无终端/断开 tty 时的 [Errno 5] Input/output error"""
    try:
        print(*args, **kwargs)
        sys.stdout.flush()
    except OSError:
        pass

def load_or_sync_data():
    """加载并对齐 512890 行情、中证红利低波指数估值与十年期国债收益率"""
    etf_file = CACHE_DIR / "sh512890_kline.csv"
    idx_file = CACHE_DIR / "h30269_index_hist.csv"
    rate_file = CACHE_DIR / "bond_rates_hist.csv"
    
    if not (etf_file.exists() and idx_file.exists() and rate_file.exists()):
        safe_print("[*] 正在从数据源拉取并缓存原始数据...")
        from data.sina_fetcher import fetch_sina_stock_kline
        import akshare as ak
        
        df_etf = fetch_sina_stock_kline(ETF_SYMBOL, datalen=3000)
        df_etf.to_csv(etf_file)
        
        df_idx = ak.stock_zh_index_hist_csindex(symbol="H30269", start_date="20190101", end_date="20261016")
        df_idx["日期"] = pd.to_datetime(df_idx["日期"])
        df_idx.set_index("日期", inplace=True)
        df_idx.to_csv(idx_file)
        
        df_rates = ak.bond_zh_us_rate()
        df_rates["日期"] = pd.to_datetime(df_rates["日期"])
        df_rates.set_index("日期", inplace=True)
        df_rates.to_csv(rate_file)
    else:
        df_etf = pd.read_csv(etf_file, index_col=0, parse_dates=True)
        df_idx = pd.read_csv(idx_file, index_col=0, parse_dates=True)
        df_rates = pd.read_csv(rate_file, index_col=0, parse_dates=True)
        
    from data.sina_fetcher import fetch_sina_stock_kline
    df_bond = fetch_sina_stock_kline(BOND_SYMBOL, datalen=3000)
    df_csi300 = fetch_sina_stock_kline("sh000300", datalen=3000)

    # 对齐共同交易日
    idx = df_etf.index.intersection(df_idx.index).intersection(df_bond.index).intersection(df_csi300.index)
    df = df_etf.loc[idx].copy().sort_index()
    df["pe"] = df_idx.loc[idx, "滚动市盈率"]
    rates_10y = df_rates["中国国债收益率10年"].dropna()
    df["rate_10y"] = rates_10y.reindex(df.index).ffill().bfill()
    df["bond_close"] = df_bond.loc[idx, "close"]
    df["csi300_close"] = df_csi300.loc[idx, "close"]
    
    return df

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算各高抛低吸策略所需的量化指标"""
    data = df.copy()
    
    # 1. 策略一: 真实波幅 ATR20 与均线中轴 EMA30
    hl = data["high"] - data["low"]
    hc = (data["high"] - data["close"].shift(1)).abs()
    lc = (data["low"] - data["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    data["atr20"] = tr.rolling(20).mean()
    data["ema30"] = data["close"].ewm(span=30, adjust=False).mean()
    
    # 2. 策略二: 股债风险溢价 (ERP) 及历史分位数 (250日滚动)
    data["ey"] = (1.0 / data["pe"]) * 100.0  # 盈利收益率 E/P %
    data["erp"] = data["ey"] - data["rate_10y"]  # ERP = 盈利收益率 - 10年国债收益率
    data["erp_pct"] = data["erp"].rolling(250, min_periods=60).apply(
        lambda x: (pd.Series(x).rank(pct=True).iloc[-1]), raw=False
    )
    
    # 3. 策略三: 乖离率 BIAS20 与相对强弱指标 RSI14
    data["ma20"] = data["close"].rolling(20).mean()
    data["bias20"] = (data["close"] - data["ma20"]) / data["ma20"] * 100.0
    
    delta = data["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    data["rsi14"] = 100 - (100 / (1 + rs))
    
    return data

def run_simulation(
    data: pd.DataFrame, 
    warmup: int = 60,
    w_overheat: float = 0.50,
    w_neutral: float = 0.75,
    w_undervalue: float = 1.00,
    th_overheat: float = 0.20,
    th_neutral: float = 0.35,
    cost_rate: float = 0.0003
):
    """
    运行策略回测撮合引擎
    交易成本: 万1 佣金 (0.0001) + 万2 滑点 (0.0002) = 0.0003 双边换手成本 (支持自定义费率)
    闲置资金: 配置十年期国债 ETF (511260)，实现真正的股债平衡与现金管理
    策略二 ERP: 支持自定义三档区域仓位与分位线阈值
    """
    valid_df = data.iloc[warmup:].copy()
    etf_ret = valid_df["close"].pct_change().fillna(0.0)
    bond_ret = valid_df["bond_close"].pct_change().fillna(0.0)
    csi_ret = valid_df["csi300_close"].pct_change().fillna(0.0)
    
    # 1. 基准: 华泰低波红利买入持有与沪深300指数买入持有
    bench_nav = (1.0 + etf_ret).cumprod()
    csi300_nav = (1.0 + csi_ret).cumprod()
    
    # 2. 策略一: 动态 ATR 通道网格策略
    w_atr = pd.Series(1.0, index=valid_df.index)
    for dt in valid_df.index:
        c = valid_df.loc[dt, "close"]
        ema = valid_df.loc[dt, "ema30"]
        atr = valid_df.loc[dt, "atr20"]
        if c >= ema + 2.0 * atr:
            w_atr.loc[dt] = 0.50
        elif c >= ema + 1.2 * atr:
            w_atr.loc[dt] = 0.75
        else:
            w_atr.loc[dt] = 1.00
            
    # 3. 策略二: ERP 股债利差大波段择时策略 (支持自定义三档仓位与分位阈值)
    w_erp = pd.Series(w_undervalue, index=valid_df.index)
    for dt in valid_df.index:
        pct = valid_df.loc[dt, "erp_pct"]
        if pct <= th_overheat:
            w_erp.loc[dt] = w_overheat
        elif pct <= th_neutral:
            w_erp.loc[dt] = w_neutral
        else:
            w_erp.loc[dt] = w_undervalue
            
    # 4. 策略三: BIAS 乖离率 + RSI 动量极值波段反转策略
    w_bias = pd.Series(1.0, index=valid_df.index)
    for dt in valid_df.index:
        bias = valid_df.loc[dt, "bias20"]
        rsi = valid_df.loc[dt, "rsi14"]
        if bias >= 2.5 and rsi >= 65:
            w_bias.loc[dt] = 0.50
        elif bias >= 1.5 and rsi >= 60:
            w_bias.loc[dt] = 0.75
        elif bias <= -1.0:
            w_bias.loc[dt] = 1.00
        else:
            w_bias.loc[dt] = w_bias.shift(1).loc[dt] if dt != valid_df.index[0] else 1.00
            
    def simulate_weights(weights_series):
        nav = [1.0]
        w_list = [weights_series.iloc[0]]
        turnovers = [weights_series.iloc[0]]
        
        for i in range(1, len(valid_df)):
            w = weights_series.iloc[i-1]  # T-1 日信号在 T 日开盘/收盘生效
            turnover = abs(w - w_list[-1])
            fee = turnover * cost_rate
            r_bond = bond_ret.iloc[i]
            r_etf = etf_ret.iloc[i]
            r_port = w * r_etf + (1.0 - w) * r_bond - fee
            nav.append(nav[-1] * (1.0 + r_port))
            w_list.append(w)
            turnovers.append(turnover)
            
        return pd.DataFrame({
            "nav": nav,
            "weight": w_list,
            "turnover": turnovers
        }, index=valid_df.index)
        
    res_s1 = simulate_weights(w_atr)
    res_s2 = simulate_weights(w_erp)
    res_s3 = simulate_weights(w_bias)
    
    # 整合回测数据
    report_df = pd.DataFrame({
        "close": valid_df["close"],
        "bench_nav": bench_nav,
        "csi300_nav": csi300_nav,
        "s1_atr_nav": res_s1["nav"],
        "s1_weight": res_s1["weight"],
        "s2_erp_nav": res_s2["nav"],
        "s2_weight": res_s2["weight"],
        "s3_bias_nav": res_s3["nav"],
        "s3_weight": res_s3["weight"]
    }, index=valid_df.index)
    
    # 计算各策略动态回撤
    for col in ["bench_nav", "csi300_nav", "s1_atr_nav", "s2_erp_nav", "s3_bias_nav"]:
        dd_col = f"dd_{col}"
        cummax = report_df[col].cummax()
        report_df[dd_col] = (report_df[col] - cummax) / cummax
        
    return report_df

def generate_trade_ledger(
    report_df: pd.DataFrame, 
    raw_df: pd.DataFrame = None, 
    strat_key: str = "s2",
    th_overheat: float = 0.20,
    th_neutral: float = 0.35
):
    """
    重构生成指定策略的券商级逐笔做 T 交易交割流水单 (Trade Ledger)
    每一笔包含: 交割日期, 标的代码, 标的名称, 操作类型(高抛/低吸), 成交价, 仓位变动, 调仓份额, 单笔做T收益率, 持仓天数, 交割状态, 量化依据
    """
    w_col = f"{strat_key}_weight" if f"{strat_key}_weight" in report_df.columns else "s2_weight"
    w_series = report_df[w_col]
    prices = report_df["close"]
    
    records = []
    prev_w = w_series.iloc[0]
    last_buy_price = prices.iloc[0]
    last_buy_date = report_df.index[0]
    
    win_count = 0
    total_closed = 0
    
    for i in range(1, len(report_df)):
        cur_w = w_series.iloc[i]
        dt = report_df.index[i]
        p = prices.iloc[i]
        
        if cur_w != prev_w:
            diff = cur_w - prev_w
            is_buy = diff > 0
            action = "低吸加仓 🔼" if is_buy else "高抛减仓 🔻"
            
            pnl_val = None
            pnl_str = "-"
            status = "调仓中"
            hold_days = (dt - last_buy_date).days
            
            if not is_buy:
                total_closed += 1
                pnl_val = (p - last_buy_price) / (last_buy_price + 1e-9)
                pnl_str = f"{pnl_val*100:+.2f}%"
                if pnl_val > 0:
                    win_count += 1
                    status = "盈利 🟢"
                else:
                    status = "亏损 🔴"
                    
            # 提取量化依据
            reason = "调仓触发"
            if raw_df is not None and dt in raw_df.index:
                if strat_key == "s2":
                    pct = raw_df.loc[dt, "erp_pct"] * 100
                    reason = f"ERP分位数={pct:.1f}% (<= {th_overheat*100:.0f}% 估值过热高抛)" if not is_buy else f"ERP分位数={pct:.1f}% (> {th_neutral*100:.0f}% 性价比良好低吸)"
                elif strat_key == "s1":
                    ema = raw_df.loc[dt, "ema30"]
                    atr = raw_df.loc[dt, "atr20"]
                    dev = (p - ema) / (atr + 1e-9)
                    reason = f"突破中轴 {dev:+.1f} ATR 上轨 (高抛减仓)" if not is_buy else f"回落中轴修复 {dev:+.1f} ATR (低吸回补)"
                elif strat_key == "s3":
                    bias = raw_df.loc[dt, "bias20"]
                    rsi = raw_df.loc[dt, "rsi14"]
                    reason = f"BIAS={bias:+.1f}%, RSI={rsi:.0f} (超买高抛)" if not is_buy else f"BIAS={bias:+.1f}%, RSI={rsi:.0f} (超跌低吸)"
                    
            records.append({
                "交割日期": dt.strftime("%Y-%m-%d"),
                "标的代码": "512890.SH",
                "标的名称": "华泰低波红利ETF",
                "操作类型": action,
                "成交价格": round(p, 3),
                "仓位调整": f"{int(prev_w*100)}% ➔ {int(cur_w*100)}%",
                "调仓幅度": f"{abs(diff)*100:.0f}%",
                "单笔盈亏": pnl_str,
                "pnl_raw": pnl_val,
                "持仓天数": f"{max(hold_days, 1)}天",
                "交割状态": status,
                "量化触发依据": reason
            })
            
            if is_buy:
                last_buy_price = p
                last_buy_date = dt
            prev_w = cur_w
            
    ledger_df = pd.DataFrame(records)
    win_rate = (win_count / total_closed * 100) if total_closed > 0 else 0.0
    return ledger_df, win_rate, total_closed, win_count

def compute_metrics(report_df: pd.DataFrame) -> pd.DataFrame:
    """计算年化收益、最大回撤、夏普比率、卡玛比率等核心绩效"""
    nav_map = {
        "⭐ 红利低波ERP利差高抛低吸策略": "s2_erp_nav",
        "华泰低波红利 (基准纯持有)": "bench_nav",
        "沪深300指数 (市场宽基)": "csi300_nav",
        "策略一: 动态 ATR 网格高抛低吸": "s1_atr_nav",
        "策略三: BIAS+RSI 极值波段高抛低吸": "s3_bias_nav"
    }
    
    days = (report_df.index[-1] - report_df.index[0]).days
    results = []
    
    for label, col in nav_map.items():
        if col not in report_df.columns:
            continue
        s = report_df[col]
        tot_ret = s.iloc[-1] - 1.0
        ann_ret = (s.iloc[-1]) ** (365.25 / days) - 1.0
        daily_r = s.pct_change().dropna()
        ann_vol = daily_r.std() * np.sqrt(250)
        sharpe = (ann_ret - 0.02) / (ann_vol + 1e-9)
        dd = report_df[f"dd_{col}"]
        max_dd = dd.min()
        calmar = ann_ret / (abs(max_dd) + 1e-9)
        alpha = ann_ret - ((report_df["bench_nav"].iloc[-1]) ** (365.25 / days) - 1.0)
        
        results.append({
            "策略名称": label,
            "累计收益率": f"{tot_ret*100:.2f}%",
            "年化收益率": f"{ann_ret*100:.2f}%",
            "超额年化收益(Alpha)": f"{alpha*100:+.2f}%",
            "年化波动率": f"{ann_vol*100:.2f}%",
            "最大回撤": f"{max_dd*100:.2f}%",
            "夏普比率": f"{sharpe:.2f}",
            "卡玛比率": f"{calmar:.2f}",
            "期末净值": f"{s.iloc[-1]:.4f}"
        })
        
    return pd.DataFrame(results)

def plot_interactive_curves(report_df: pd.DataFrame, save_path: str = "./reports/dividend_swing_backtest.html"):
    """生成专业交互式 HTML 双子图（净值走势图 + 动态水下回撤图）"""
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.70, 0.30],
        subplot_titles=("华泰低波红利 (512890) 高抛低吸量化策略 vs 纯持有 vs 沪深300 (2019-2026)", "动态水下回撤曲线对比 (Drawdown)")
    )
    
    colors = {
        "s2_erp_nav": ("#EF4444", "⭐ 红利低波ERP利差高抛低吸策略", 2.6, "solid"),
        "bench_nav": ("#64748B", "华泰低波红利 (基准持有)", 1.8, "dot"),
        "csi300_nav": ("#D97706", "沪深300指数 (市场宽基)", 1.8, "solid")
    }
    
    for key, (color, name, width, dash_style) in colors.items():
        if key not in report_df.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=report_df.index,
                y=report_df[key],
                mode="lines",
                name=name,
                line=dict(color=color, width=width, dash=dash_style),
                hovertemplate=f"<b>{name}</b><br>日期: %{{x|%Y-%m-%d}}<br>净值: %{{y:.4f}}<extra></extra>"
            ),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Scatter(
                x=report_df.index,
                y=report_df[f"dd_{key}"] * 100,
                mode="lines",
                name=f"{name} 回撤",
                line=dict(color=color, width=1.2),
                showlegend=False,
                hovertemplate=f"<b>{name} 回撤</b><br>日期: %{{x|%Y-%m-%d}}<br>回撤: %{{y:.2f}}%<extra></extra>"
            ),
            row=2, col=1
        )
        
    fig.update_layout(
        template="plotly_white",
        height=720,
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            font=dict(size=12)
        ),
        margin=dict(l=40, r=40, t=80, b=40)
    )
    fig.update_yaxes(title_text="累计净值 (基准 1.00)", row=1, col=1)
    fig.update_yaxes(title_text="回撤幅度 (%)", row=2, col=1)
    
    fig.write_html(save_path)
    safe_print(f"[✓] 交互式净值曲线图已生成并保存至: {save_path}")

def run_dividend_backtest(
    w_overheat: float = 0.50,
    w_neutral: float = 0.75,
    w_undervalue: float = 1.00,
    th_overheat: float = 0.20,
    th_neutral: float = 0.35,
    cost_rate: float = 0.0003
):
    safe_print("[*] 正在加载 512890 及相关资产数据...")
    df = load_or_sync_data()
    safe_print(f"[*] 数据加载完成: {len(df)} 交易日 ({df.index.min().strftime('%Y-%m-%d')} ~ {df.index.max().strftime('%Y-%m-%d')})")
    
    safe_print("[*] 正在计算技术与宏观指标 (ATR, EMA, ERP, BIAS, RSI)...")
    raw_df = compute_indicators(df)
    
    safe_print(f"[*] 正在运行真实撮合交易模拟与净值计算 (过热仓位={w_overheat*100:.0f}%, 观察带={w_neutral*100:.0f}%, 低估仓位={w_undervalue*100:.0f}%)...")
    report_df = run_simulation(
        raw_df,
        w_overheat=w_overheat,
        w_neutral=w_neutral,
        w_undervalue=w_undervalue,
        th_overheat=th_overheat,
        th_neutral=th_neutral,
        cost_rate=cost_rate
    )
    
    # 导出日度明细 CSV
    csv_path = REPORT_DIR / "dividend_swing_daily_report.csv"
    report_df.to_csv(csv_path)
    safe_print(f"[✓] 回测每日净值与持仓明细已保存至: {csv_path}")
    
    # 生成默认策略二的券商交割单
    ledger_df, win_rate, tot, wins = generate_trade_ledger(
        report_df, 
        raw_df, 
        strat_key="s2",
        th_overheat=th_overheat,
        th_neutral=th_neutral
    )
    ledger_path = REPORT_DIR / "dividend_swing_trade_ledger.csv"
    ledger_df.to_csv(ledger_path, index=False)
    safe_print(f"[✓] 策略二券商交割账单已生成: 共 {tot} 笔平仓, 胜率 {win_rate:.1f}%")
    
    # 计算并打印绩效
    metrics_df = compute_metrics(report_df)
    safe_print("\n" + "="*80)
    safe_print("华泰低波红利 (512890) 高抛低吸量化策略核心绩效统计表 (2019-04 ~ 2026-10)")
    safe_print("="*80)
    safe_print(metrics_df.to_string(index=False))
    safe_print("="*80 + "\n")
    
    # 生成交互式 HTML 图表
    html_path = REPORT_DIR / "dividend_swing_backtest.html"
    plot_interactive_curves(report_df, str(html_path))
    
    return report_df, metrics_df, ledger_df

if __name__ == "__main__":
    run_dividend_backtest()
