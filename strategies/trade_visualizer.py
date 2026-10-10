#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单标的交易行为复盘与 K 线买卖标记可视化
1. 自动生成标准量化交割流水账单 (Trade Ledger: 买入/卖出/价格/收益率/持仓天数)
2. 在 K 线图上精确标记交割买卖点并联动显示持仓盈亏连线
"""

import os
import glob
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
from data.etf_pool import ETF_POOL

def get_symbol_display_name(symbol):
    code = symbol.lower().strip()
    if code in ETF_POOL:
        return ETF_POOL[code]
    name_map = {
        "sh600519": "贵州茅台", "sz000858": "五粮液", "sh601318": "中国平安",
        "sz000001": "平安银行", "sh600036": "招商银行", "sz002594": "比亚迪",
        "sz300750": "宁德时代", "sh600276": "恒瑞医药", "sh600900": "长江电力",
        "sh600030": "中信证券", "sz000333": "美的集团", "sh601899": "紫金矿业"
    }
    return name_map.get(code, code.upper())

def load_symbol_kline(symbol, start_time, end_time):
    """
    获取指定标的的 OHLCV 日K线
    """
    code = symbol.lower().strip()
    cache_file = f"./data/sina_cache/{code}.csv"
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col="datetime", parse_dates=True)
        sub_df = df.loc[(df.index >= pd.to_datetime(start_time)) & (df.index <= pd.to_datetime(end_time))].copy()
        if len(sub_df) > 0:
            return sub_df

    # 尝试从 Qlib 读取
    try:
        import qlib
        from qlib.data import D
        provider_uri = os.path.abspath("./data/cn_data")
        qlib.init(provider_uri=provider_uri, region="cn")
        
        q_code = code.upper()
        if not (q_code.startswith("SH") or q_code.startswith("SZ")):
            q_code = ("SH" if q_code.startswith("6") or q_code.startswith("9") else "SZ") + q_code
            
        df = D.features([q_code], fields=["$open", "$high", "$low", "$close", "$volume"], start_time=str(start_time), end_time=str(end_time))
        if df is not None and len(df) > 0:
            df = df.droplevel("instrument")
            df.columns = ["open", "high", "low", "close", "volume"]
            return df
    except Exception as e:
        pass
        
    return pd.DataFrame()

def generate_full_trade_ledger(report_df):
    """
    从回测每日持仓表中，重构生成完整的券商级交割流水单 (Trade Ledger)
    每一笔包含: 标的代码, 标的名称, 买入日, 买入价, 卖出日, 卖出价, 持仓天数, 盈亏比例, 状态
    """
    if "sample_stocks" not in report_df.columns:
        return pd.DataFrame()

    dates = report_df.index.sort_values()
    start_dt = dates.min()
    end_dt = dates.max()

    # 收集所有出现过的股票
    all_symbols = set()
    for s_str in report_df["sample_stocks"].dropna():
        for s in str(s_str).split(","):
            s = s.strip().lower()
            if s:
                all_symbols.add(s)

    # 预加载所有 K 线以便精准取买卖价格
    klines = {}
    for sym in all_symbols:
        k = load_symbol_kline(sym, start_dt, end_dt)
        if len(k) > 0:
            klines[sym] = k

    ledger_records = []

    for sym in sorted(list(all_symbols)):
        k_df = klines.get(sym)
        holding_info = None
        
        for dt in dates:
            stocks_str = str(report_df.loc[dt, "sample_stocks"])
            current_stocks = [s.strip().lower() for s in stocks_str.split(",") if s.strip()]
            is_in = sym in current_stocks

            if is_in and holding_info is None:
                # 买入开仓
                buy_price = k_df.loc[dt, "close"] if (k_df is not None and dt in k_df.index) else 1.0
                holding_info = {
                    "symbol": sym,
                    "name": get_symbol_display_name(sym),
                    "buy_date": dt,
                    "buy_price": buy_price,
                }
            elif not is_in and holding_info is not None:
                # 卖出平仓
                sell_price = k_df.loc[dt, "close"] if (k_df is not None and dt in k_df.index) else holding_info["buy_price"]
                pnl_pct = (sell_price - holding_info["buy_price"]) / holding_info["buy_price"]
                hold_days = (dt - holding_info["buy_date"]).days

                ledger_records.append({
                    "标的代码": sym,
                    "标的名称": holding_info["name"],
                    "买入日期": holding_info["buy_date"].strftime("%Y-%m-%d"),
                    "买入价格": round(holding_info["buy_price"], 3),
                    "卖出日期": dt.strftime("%Y-%m-%d"),
                    "卖出价格": round(sell_price, 3),
                    "持仓天数": max(hold_days, 1),
                    "单笔收益率": f"{pnl_pct * 100:+.2f}%",
                    "pnl_raw": pnl_pct,
                    "交割状态": "盈利 🟢" if pnl_pct > 0 else "亏损 🔴"
                })
                holding_info = None

        # 截至回测最后一天仍在持仓中的标的
        if holding_info is not None:
            last_dt = dates[-1]
            cur_price = k_df.loc[last_dt, "close"] if (k_df is not None and last_dt in k_df.index) else holding_info["buy_price"]
            pnl_pct = (cur_price - holding_info["buy_price"]) / holding_info["buy_price"]
            hold_days = (last_dt - holding_info["buy_date"]).days
            ledger_records.append({
                "标的代码": sym,
                "标的名称": holding_info["name"],
                "买入日期": holding_info["buy_date"].strftime("%Y-%m-%d"),
                "买入价格": round(holding_info["buy_price"], 3),
                "卖出日期": "当前仍持仓",
                "卖出价格": round(cur_price, 3),
                "持仓天数": max(hold_days, 1),
                "单笔收益率": f"{pnl_pct * 100:+.2f}%",
                "pnl_raw": pnl_pct,
                "交割状态": "持有中 ⏳"
            })

    if not ledger_records:
        return pd.DataFrame()

    ledger_df = pd.DataFrame(ledger_records)
    ledger_df.sort_values(by="买入日期", ascending=False, inplace=True)
    return ledger_df

def plot_stock_kline_with_trades(kline_df, symbol_trades_ledger, symbol_name="标的", highlight_trade_idx=None):
    """兼容旧接口，直接指向同花顺专业 K 线渲染引擎"""
    return plot_tonghuashun_kline_with_trades(kline_df, symbol_trades_ledger, symbol_name)

def plot_tonghuashun_kline_with_trades(kline_df, symbol_trades_ledger, symbol_name="标的"):
    """
    同花顺经典风格专业 K 线与交割复盘图表：
    1. 同花顺极黑底色 (#0e1017) 与微光网格
    2. MA5 (黄), MA10 (粉紫), MA20 (青绿), MA60 (白) 均线系统
    3. 同花顺正版操盘先锋 [B] 买入徽章 (最低价下方) 与 [S] 卖出徽章 (最高价上方)
    4. 买卖点点状连接线 (红涨绿跌盈亏标注)
    5. 下方成交量柱状图 (VOL) 配合 VOL5, VOL10 量均线
    6. 右侧经典价格轴坐标 (side='right')
    7. 十字查价准线 (Spikelines) 与无缝跳过周末 (rangebreaks)
    """
    if kline_df is None or len(kline_df) == 0:
        return None

    df = kline_df.copy()
    # 计算均线系统 (MA5, MA10, MA20, MA60)
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()

    # 计算成交量均线 (VOL5, VOL10)
    df["vma5"] = df["volume"].rolling(5).mean()
    df["vma10"] = df["volume"].rolling(10).mean()

    # 最新价与涨跌
    last_close = df["close"].iloc[-1]
    prev_close = df["close"].iloc[-2] if len(df) > 1 else last_close
    chg_pct = (last_close - prev_close) / prev_close * 100

    # 创建双子图：上方 K 线主图 (72%)，下方成交量副图 (28%)
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.72, 0.28]
    )

    # 1. 主图：同花顺经典红涨绿跌蜡烛图
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="K线",
            increasing_line_color="#ff3333",
            increasing_fillcolor="#ff3333",
            decreasing_line_color="#00b060",
            decreasing_fillcolor="#00b060",
            hoverlabel=dict(bgcolor="#1c202e", font=dict(color="#ffffff", size=12))
        ),
        row=1, col=1
    )

    # 2. 同花顺四均线 (MA5: 黄, MA10: 紫, MA20: 青绿, MA60: 白)
    ma_colors = [
        ("ma5", "MA5", "#fadb14", 1.1),
        ("ma10", "MA10", "#e056fd", 1.1),
        ("ma20", "MA20", "#00d2d3", 1.2),
        ("ma60", "MA60", "#ffffff", 1.2)
    ]
    for col, name, color, w in ma_colors:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df[col],
                mode="lines",
                name=name,
                line=dict(color=color, width=w),
                hoverinfo="y+name",
                hoverlabel=dict(bgcolor="#1c202e")
            ),
            row=1, col=1
        )

    # 3. 买卖交割打点与同花顺 [B] / [S] 操盘徽章
    buy_dates, buy_prices, buy_texts, buy_hover = [], [], [], []
    sell_dates, sell_prices, sell_texts, sell_hover = [], [], [], []

    if symbol_trades_ledger is not None and len(symbol_trades_ledger) > 0:
        for idx, row in symbol_trades_ledger.iterrows():
            b_dt = pd.to_datetime(row["买入日期"])
            b_p = row["买入价格"]
            s_dt_str = row["卖出日期"]
            s_p = row["卖出价格"]
            pnl_str = row["单笔收益率"]

            # 买入点打在当天下影线下方
            if b_dt in df.index:
                k_row = df.loc[b_dt]
                buy_dates.append(b_dt)
                buy_prices.append(k_row["low"] * 0.982)
                buy_texts.append("B")
                buy_hover.append(
                    f"<b>【同花顺操盘信号: 买入开仓 B】</b><br>"
                    f"标的: {symbol_name}<br>"
                    f"日期: {row['买入日期']}<br>"
                    f"买入价: ¥{b_p:.3f}<br>"
                    f"状态: 买入建仓"
                )

            # 卖出点打在当天上影线上方
            if s_dt_str != "当前仍持仓":
                s_dt = pd.to_datetime(s_dt_str)
                if s_dt in df.index:
                    k_row = df.loc[s_dt]
                    sell_dates.append(s_dt)
                    sell_prices.append(k_row["high"] * 1.018)
                    sell_texts.append("S")
                    is_win = "+" in str(pnl_str)
                    sell_hover.append(
                        f"<b>【同花顺操盘信号: 卖出平仓 S】</b><br>"
                        f"标的: {symbol_name}<br>"
                        f"卖出日期: {s_dt_str}<br>"
                        f"卖出价: ¥{s_p:.3f}<br>"
                        f"持仓周期: {row['持仓天数']} 天<br>"
                        f"本笔收益: <b>{pnl_str}</b> {'🟢 盈利' if is_win else '🔴 亏损'}"
                    )

                    # 绘制连接这笔买卖的同花顺盈亏虚线
                    line_color = "rgba(255, 51, 51, 0.75)" if is_win else "rgba(0, 176, 96, 0.75)"
                    fig.add_trace(
                        go.Scatter(
                            x=[b_dt, s_dt],
                            y=[b_p, s_p],
                            mode="lines+markers",
                            name=f"盈亏连线 ({pnl_str})",
                            line=dict(color=line_color, width=2, dash="dot"),
                            marker=dict(size=4, color=line_color),
                            hoverinfo="text",
                            hovertext=f"交割闭环: {row['买入日期']} ➜ {s_dt_str} | 收益率: {pnl_str} ({row['持仓天数']}天)",
                            showlegend=False
                        ),
                        row=1, col=1
                    )

    # 4. 渲染同花顺风格 [B] 圆形徽章 (红色圆底白字，醒目经典)
    if buy_dates:
        fig.add_trace(
            go.Scatter(
                x=buy_dates,
                y=buy_prices,
                mode="markers+text",
                name="买入开仓 [B]",
                text=buy_texts,
                textposition="middle center",
                textfont=dict(color="#ffffff", size=10, family="Arial Black"),
                marker=dict(
                    symbol="circle",
                    size=17,
                    color="#e74c3c",
                    line=dict(width=1.5, color="#ffffff")
                ),
                hovertext=buy_hover,
                hoverinfo="text"
            ),
            row=1, col=1
        )

    # 5. 渲染同花顺风格 [S] 圆形徽章 (蓝色/深绿圆底白字)
    if sell_dates:
        fig.add_trace(
            go.Scatter(
                x=sell_dates,
                y=sell_prices,
                mode="markers+text",
                name="卖出平仓 [S]",
                text=sell_texts,
                textposition="middle center",
                textfont=dict(color="#ffffff", size=10, family="Arial Black"),
                marker=dict(
                    symbol="circle",
                    size=17,
                    color="#2980b9",
                    line=dict(width=1.5, color="#ffffff")
                ),
                hovertext=sell_hover,
                hoverinfo="text"
            ),
            row=1, col=1
        )

    # 6. 下方成交量副图 (VOL) + 量均线 (VOL5, VOL10)
    vol_colors = ["#ff3333" if c >= o else "#00b060" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["volume"],
            name="成交量",
            marker_color=vol_colors,
            opacity=0.85,
            hoverlabel=dict(bgcolor="#1c202e")
        ),
        row=2, col=1
    )
    # VOL5 & VOL10
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["vma5"],
            mode="lines", name="VOL5",
            line=dict(color="#fadb14", width=1.0),
            hoverinfo="y+name",
            hoverlabel=dict(bgcolor="#1c202e")
        ),
        row=2, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["vma10"],
            mode="lines", name="VOL10",
            line=dict(color="#e056fd", width=1.0),
            hoverinfo="y+name",
            hoverlabel=dict(bgcolor="#1c202e")
        ),
        row=2, col=1
    )

    # 7. 同花顺专业图表配置：深色底 (#0e1017)、右侧价格刻度、十字准线、去周末断层
    fig.update_xaxes(
        rangebreaks=[dict(bounds=["sat", "mon"])],
        showgrid=True,
        gridcolor="#1b1e2b",
        zerolinecolor="#1b1e2b",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikedash="solid",
        spikecolor="#57606f",
        rangeslider_visible=False,  # 必须关闭！避免所有买卖标记与缩略图挤入滑块导致错位
        row=1, col=1
    )
    fig.update_xaxes(
        rangebreaks=[dict(bounds=["sat", "mon"])],
        showgrid=True,
        gridcolor="#1b1e2b",
        zerolinecolor="#1b1e2b",
        rangeslider_visible=False,  # 彻底关闭破坏性滑块
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikedash="solid",
        spikecolor="#57606f",
        row=2, col=1
    )

    # 右侧价格轴 (同花顺最正统的右侧盘口)
    fig.update_yaxes(
        title_text="价格(元)",
        side="right",
        autorange=True,
        fixedrange=False,
        showgrid=True,
        gridcolor="#1b1e2b",
        zerolinecolor="#1b1e2b",
        tickfont=dict(color="#c8d6e5", size=11),
        title_font=dict(color="#8395a7", size=11),
        row=1, col=1
    )
    fig.update_yaxes(
        title_text="成交量",
        side="right",
        autorange=True,
        fixedrange=False,
        showgrid=True,
        gridcolor="#1b1e2b",
        zerolinecolor="#1b1e2b",
        tickfont=dict(color="#c8d6e5", size=10),
        title_font=dict(color="#8395a7", size=10),
        row=2, col=1
    )

    # 同花顺顶部标题状态栏
    title_html = (
        f"<span style='color:#ffffff; font-size:15px; font-weight:bold;'>{symbol_name}</span> "
        f"<span style='color:{'#ff3333' if chg_pct>=0 else '#00b060'}; font-size:14px; font-weight:bold; margin-left:10px;'>"
        f"¥{last_close:.3f} ({chg_pct:+.2f}%)</span>"
    )

    fig.update_layout(
        title=dict(
            text=title_html,
            x=0.01, y=0.97,
            font=dict(family="PingFang SC, Microsoft YaHei, sans-serif")
        ),
        xaxis_rangeslider_visible=False,
        paper_bgcolor="#0c0d14",
        plot_bgcolor="#0c0d14",
        height=660,
        hovermode="x unified",
        dragmode="zoom",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1.0,
            font=dict(color="#dcdde1", size=11),
            bgcolor="rgba(12,13,20,0.7)"
        ),
        margin=dict(l=15, r=55, t=55, b=25)
    )
    return fig

