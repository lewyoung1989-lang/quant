#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于行业成熟金融标准 Apache ECharts 的同花顺专业 K 线复盘组件
支持：
1. 彻底解决放大/缩小 Y 轴失真、断层空白、买卖标记掉落等问题
2. 支持【单笔交割深度聚焦放大】：选定某一条交割明细，K 线图立即平滑放大该交割范围的数据！
3. 顶部支持快捷单笔选择下拉框、1月/3月/半年/1年/全部周期切换
4. 鼠标滚轮平滑缩放、鼠标平移拖拽，同花顺纯黑主题 (#0e1017)
"""

import os
import json
import pandas as pd

def build_tonghuashun_echarts_html(kline_df, symbol_trades_ledger, symbol_name="标的", chart_height=640, focus_trade_idx=None):
    if kline_df is None or len(kline_df) == 0:
        return "<div style='color:#fff; padding:20px; text-align:center;'>暂无日K线数据</div>"

    df = kline_df.copy()
    df.sort_index(inplace=True)

    # 1. 整理时间轴与 OHLCV 数据
    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    # ECharts Candlestick: [open, close, lowest, highest]
    kline_values = []
    volumes = []
    
    for i, (_, row) in enumerate(df.iterrows()):
        o, c, l, h, v = float(row["open"]), float(row["close"]), float(row["low"]), float(row["high"]), float(row.get("volume", 0))
        kline_values.append([round(o, 3), round(c, 3), round(l, 3), round(h, 3)])
        # volume: [index, volume, 1 for up / -1 for down]
        volumes.append([i, round(v, 2), 1 if c >= o else -1])

    # 2. 计算均线系统 (MA5, MA10, MA20, MA60)
    def calc_ma(day_count):
        ma = df["close"].rolling(day_count).mean()
        return [None if pd.isna(x) else round(float(x), 3) for x in ma]

    ma5 = calc_ma(5)
    ma10 = calc_ma(10)
    ma20 = calc_ma(20)
    ma60 = calc_ma(60)

    # 计算成交量均线
    vma5 = [None if pd.isna(x) else round(float(x), 1) for x in df["volume"].rolling(5).mean()]
    vma10 = [None if pd.isna(x) else round(float(x), 1) for x in df["volume"].rolling(10).mean()]

    # 3. 解析交割买卖标记与闭环连线
    mark_points = []
    mark_lines = []
    trades_list = []
    date_to_idx = {d: i for i, d in enumerate(dates)}

    if symbol_trades_ledger is not None and len(symbol_trades_ledger) > 0:
        for t_idx, row in symbol_trades_ledger.reset_index(drop=True).iterrows():
            b_dt_str = str(row["买入日期"])
            b_p = float(row["买入价格"])
            s_dt_str = str(row["卖出日期"])
            s_p = float(row["卖出价格"])
            pnl_str = str(row["单笔收益率"])
            hold_days = int(row.get("持仓天数", 1))

            trades_list.append({
                "idx": t_idx,
                "buyDate": b_dt_str,
                "buyPrice": b_p,
                "sellDate": s_dt_str,
                "sellPrice": s_p,
                "pnl": pnl_str,
                "holdDays": hold_days,
                "status": str(row.get("交割状态", ""))
            })

            # 判断交割状态
            is_closed = (s_dt_str != "当前仍持仓")
            is_win = "+" in pnl_str

            # 买入点 B (锚定在当天下影线最底端 low_p)
            if b_dt_str in date_to_idx:
                idx = date_to_idx[b_dt_str]
                low_p = kline_values[idx][2]
                
                # 如果是最新未平仓交易，标记为【建仓持股 B】
                b_badge_name = f"买入 [B] (第{t_idx+1}笔)" if is_closed else f"持仓底仓 [B] (第{t_idx+1}笔-未平仓)"
                b_color = "#ff4757" if is_closed else "#ff6b81"
                
                mark_points.append({
                    "name": b_badge_name,
                    "coord": [b_dt_str, low_p],
                    "value": "B",
                    "symbol": "circle",
                    "symbolSize": 22,
                    "symbolOffset": [0, 16],
                    "tradeIdx": t_idx,
                    "itemStyle": {
                        "color": b_color,
                        "borderColor": "#ffffff",
                        "borderWidth": 1.5,
                        "shadowBlur": 6,
                        "shadowColor": "rgba(255, 71, 87, 0.8)"
                    },
                    "label": {
                        "show": True,
                        "formatter": "B",
                        "color": "#ffffff",
                        "fontWeight": "bold",
                        "fontSize": 11
                    },
                    "tooltip": {
                        "formatter": f"<b>【买入建仓 B】(交割 #{t_idx+1})</b><br>日期: {b_dt_str}<br>买入价: ¥{b_p:.3f}<br>对应卖出: {s_dt_str if is_closed else '⏳ 截至目前仍全仓持有中'}<br>提示: 点击可放大该笔交割范围"
                    }
                })

            # 卖出点 S (锚定在当天上影线最顶端 high_p)
            if is_closed and s_dt_str in date_to_idx:
                idx = date_to_idx[s_dt_str]
                high_p = kline_values[idx][3]
                # 盈利卖出用明亮活力绿色/薄荷绿，亏损卖出用灰蓝色，与红色的买入 B 形成鲜明色彩反差，绝不混淆！
                s_color = "#00b894" if is_win else "#0984e3"
                mark_points.append({
                    "name": f"卖出 [S] (第{t_idx+1}笔)",
                    "coord": [s_dt_str, high_p],
                    "value": "S",
                    "symbol": "circle",
                    "symbolSize": 22,
                    "symbolOffset": [0, -16],
                    "tradeIdx": t_idx,
                    "itemStyle": {
                        "color": s_color,
                        "borderColor": "#ffffff",
                        "borderWidth": 1.5,
                        "shadowBlur": 6,
                        "shadowColor": "rgba(0, 184, 148, 0.8)" if is_win else "rgba(9, 132, 227, 0.8)"
                    },
                    "label": {
                        "show": True,
                        "formatter": "S",
                        "color": "#ffffff",
                        "fontWeight": "bold",
                        "fontSize": 11
                    },
                    "tooltip": {
                        "formatter": f"<b>【卖出平仓 S】(交割 #{t_idx+1})</b><br>卖出日期: {s_dt_str}<br>卖出价: ¥{s_p:.3f}<br>持仓天数: {hold_days} 天<br>单笔收益: <b>{pnl_str}</b> {'🟢 盈利' if is_win else '🔴 亏损'}<br>对应买入: {b_dt_str} (¥{b_p:.3f})"
                    }
                })
            elif not is_closed and b_dt_str in date_to_idx:
                # 若当前仍持仓，在 K 线最新收盘处附带一个“持”状态标识，明确告知用户当前是持仓中状态
                last_dt_str = dates[-1]
                last_idx = date_to_idx.get(last_dt_str, len(dates)-1)
                last_high = kline_values[last_idx][3]
                mark_points.append({
                    "name": f"当前持仓中 (第{t_idx+1}笔)",
                    "coord": [last_dt_str, last_high],
                    "value": "持",
                    "symbol": "roundRect",
                    "symbolSize": [36, 20],
                    "symbolOffset": [0, -16],
                    "tradeIdx": t_idx,
                    "itemStyle": {
                        "color": "#e67e22",
                        "borderColor": "#ffffff",
                        "borderWidth": 1.2
                    },
                    "label": {
                        "show": True,
                        "formatter": "持仓中",
                        "color": "#ffffff",
                        "fontWeight": "bold",
                        "fontSize": 9
                    },
                    "tooltip": {
                        "formatter": f"<b>【当前持仓状态: 仍在持仓中 ⏳】</b><br>开仓买入日: {b_dt_str} (¥{b_p:.3f})<br>当前浮动盈亏: <b>{pnl_str}</b><br>已持仓天数: {hold_days} 天"
                    }
                })

            # 盈亏连线与持仓线
            if is_closed and s_dt_str in date_to_idx and b_dt_str in date_to_idx:
                line_color = "#00b894" if is_win else "#0984e3"
                mark_lines.append([
                    {
                        "name": f"#{t_idx+1} {pnl_str}",
                        "coord": [b_dt_str, b_p],
                        "lineStyle": {
                            "color": line_color,
                            "type": "dashed",
                            "width": 1.8,
                            "opacity": 0.85
                        }
                    },
                    {
                        "coord": [s_dt_str, s_p]
                    }
                ])
            elif not is_closed and b_dt_str in date_to_idx:
                # 若当前仍持仓，从买入点连线至最新一天，直观展示持仓浮动盈亏
                last_dt_str = dates[-1]
                last_idx = date_to_idx.get(last_dt_str, len(dates)-1)
                last_close = kline_values[last_idx][1]
                mark_lines.append([
                    {
                        "name": f"持仓中: {pnl_str}",
                        "coord": [b_dt_str, b_p],
                        "lineStyle": {
                            "color": "#e67e22",
                            "type": "dotted",
                            "width": 2.0,
                            "opacity": 0.9
                        }
                    },
                    {
                        "coord": [last_dt_str, last_close]
                    }
                ])

    last_close = df["close"].iloc[-1]
    prev_close = df["close"].iloc[-2] if len(df) > 1 else last_close
    chg_pct = (last_close - prev_close) / prev_close * 100

    # 4. 计算初始放大视野 (如果指定了 focus_trade_idx，直接聚焦)
    init_start_pct = 0
    init_end_pct = 100
    init_focus_note = ""

    if focus_trade_idx is not None and 0 <= focus_trade_idx < len(trades_list):
        t = trades_list[focus_trade_idx]
        b_dt = t["buyDate"]
        s_dt = t["sellDate"]
        b_i = date_to_idx.get(b_dt, 0)
        s_i = date_to_idx.get(s_dt, len(dates) - 1)
        # 向前取12日缓冲，向后取15日缓冲
        start_i = max(0, b_i - 12)
        end_i = min(len(dates) - 1, s_i + 15)
        init_start_pct = max(0, int((start_i / len(dates)) * 100))
        init_end_pct = min(100, int((end_i / len(dates)) * 100) + 1)
        init_focus_note = f"🔍 已聚焦放大第 {focus_trade_idx+1} 笔交割 [{b_dt} ~ {s_dt}] 收益: {t['pnl']}"

    safe_focus_idx = int(focus_trade_idx) if focus_trade_idx is not None else -1

    chart_data = {
        "dates": dates,
        "klineValues": kline_values,
        "volumes": volumes,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma60": ma60,
        "vma5": vma5,
        "vma10": vma10,
        "markPoints": mark_points,
        "markLines": mark_lines,
        "tradesList": trades_list,
        "symbolName": symbol_name,
        "lastClose": round(last_close, 3),
        "chgPct": round(chg_pct, 2),
        "focusTradeIdx": safe_focus_idx
    }

    def safe_json_default(obj):
        if hasattr(obj, "item"):  # numpy scalars like np.int64, np.float64
            return obj.item()
        if hasattr(obj, "__int__"):
            return int(obj)
        if hasattr(obj, "__float__"):
            return float(obj)
        return str(obj)

    json_str = json.dumps(chart_data, default=safe_json_default, ensure_ascii=False)

    # 构造下拉选择 option 列表
    trade_options_html = '<option value="all">🔍 全景视图 (全部交割)</option>'
    for t in trades_list:
        sel_attr = 'selected' if (safe_focus_idx >= 0 and t['idx'] == safe_focus_idx) else ''
        trade_options_html += f'<option value="{t["idx"]}" {sel_attr}>第 {t["idx"]+1} 笔: {t["buyDate"]} ➜ {t["sellDate"]} ({t["pnl"]})</option>'

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: #0e1017;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
            color: #e1e6eb;
            overflow: hidden;
            width: 100%;
            height: 100%;
        }}
        #kline_container {{
            width: 100%;
            height: {chart_height}px;
        }}
        .ths-header {{
            position: absolute;
            top: 8px;
            left: 16px;
            z-index: 10;
            display: flex;
            align-items: baseline;
            gap: 12px;
            pointer-events: none;
        }}
        .ths-title {{
            font-size: 15px;
            font-weight: bold;
            color: #ffffff;
        }}
        .ths-price {{
            font-size: 15px;
            font-weight: bold;
            color: {'#ff3333' if chg_pct >= 0 else '#00b060'};
        }}
        .ths-badge {{
            font-size: 11px;
            padding: 2px 6px;
            background: #1e2433;
            border-radius: 3px;
            color: #8c9ba5;
        }}
        .ths-focus-alert {{
            font-size: 12px;
            font-weight: bold;
            color: #fadb14;
            background: rgba(250, 219, 20, 0.15);
            padding: 2px 8px;
            border-radius: 4px;
            border: 1px solid rgba(250, 219, 20, 0.4);
            display: {'inline-block' if init_focus_note else 'none'};
        }}
        .ths-controls {{
            position: absolute;
            top: 8px;
            right: 20px;
            z-index: 10;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .ths-select {{
            background: #151924;
            border: 1px solid #fadb14;
            color: #fadb14;
            font-weight: 500;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            cursor: pointer;
            outline: none;
        }}
        .ths-select option {{
            background: #151924;
            color: #ffffff;
        }}
        .ths-btn {{
            background: #1a1f2c;
            border: 1px solid #2e384d;
            color: #c8d6e5;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 11px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .ths-btn:hover, .ths-btn.active {{
            background: #e74c3c;
            border-color: #e74c3c;
            color: #ffffff;
        }}
    </style>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
</head>
<body>
    <div class="ths-header">
        <span class="ths-title">{symbol_name}</span>
        <span class="ths-price">¥{last_close:.3f} ({chg_pct:+.2f}%)</span>
        <span class="ths-badge">同花顺操盘复盘模式</span>
        <span id="focusAlertText" class="ths-focus-alert">{init_focus_note}</span>
    </div>
    <div class="ths-controls">
        <select id="tradeFocusSelect" class="ths-select" onchange="focusTrade(this.value)">
            {trade_options_html}
        </select>
        <button class="ths-btn" onclick="zoomRange(30)">1月</button>
        <button class="ths-btn" onclick="zoomRange(90)">3月</button>
        <button class="ths-btn" onclick="zoomRange(180)">半年</button>
        <button class="ths-btn" onclick="zoomRange(365)">1年</button>
        <button id="btn_all" class="ths-btn {'active' if focus_trade_idx is None else ''}" onclick="zoomRange('all')">全貌</button>
    </div>
    <div id="kline_container"></div>

    <script>
        const chartData = {json_str};
        const dates = chartData.dates;
        const klineValues = chartData.klineValues;
        const tradesList = chartData.tradesList || [];
        const totalCount = dates.length;

        const chartDom = document.getElementById('kline_container');
        const myChart = echarts.init(chartDom, null, {{ renderer: 'canvas' }});

        const UP_COLOR = '#ff3333';
        const DOWN_COLOR = '#00b060';

        const option = {{
            backgroundColor: '#0e1017',
            animation: true,
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{
                    type: 'cross',
                    link: [{{ xAxisIndex: 'all' }}],
                    lineStyle: {{ color: '#636e72', width: 1, type: 'dashed' }}
                }},
                backgroundColor: 'rgba(20, 24, 35, 0.94)',
                borderColor: '#2e384d',
                borderWidth: 1,
                textStyle: {{ color: '#f1f2f6', fontSize: 12 }},
                position: function (pos, params, el, elRect, size) {{
                    const obj = {{ top: 40 }};
                    obj[['left', 'right'][+(pos[0] < size.viewSize[0] / 2)]] = 20;
                    return obj;
                }}
            }},
            axisPointer: {{
                link: [{{ xAxisIndex: 'all' }}],
                label: {{ backgroundColor: '#2d3436' }}
            }},
            legend: {{
                top: 38,
                left: 16,
                itemWidth: 12,
                itemHeight: 8,
                textStyle: {{ color: '#8c9ba5', fontSize: 11 }},
                data: ['K线', 'MA5', 'MA10', 'MA20', 'MA60', '成交量', 'VOL5', 'VOL10']
            }},
            grid: [
                {{ left: 20, right: 65, top: 65, height: '60%' }},
                {{ left: 20, right: 65, top: '72%', height: '16%' }}
            ],
            xAxis: [
                {{
                    type: 'category',
                    data: dates,
                    boundaryGap: true,
                    axisLine: {{ lineStyle: {{ color: '#222736' }} }},
                    axisLabel: {{ show: false }},
                    axisTick: {{ show: false }},
                    splitLine: {{ show: true, lineStyle: {{ color: '#161a25' }} }},
                    min: 'dataMin', max: 'dataMax'
                }},
                {{
                    type: 'category',
                    gridIndex: 1,
                    data: dates,
                    boundaryGap: true,
                    axisLine: {{ lineStyle: {{ color: '#222736' }} }},
                    axisLabel: {{ color: '#8c9ba5', fontSize: 10 }},
                    axisTick: {{ lineStyle: {{ color: '#222736' }} }},
                    splitLine: {{ show: true, lineStyle: {{ color: '#161a25' }} }},
                    min: 'dataMin', max: 'dataMax'
                }}
            ],
            yAxis: [
                {{
                    type: 'value',
                    scale: true,
                    position: 'right',
                    axisLine: {{ lineStyle: {{ color: '#222736' }} }},
                    axisLabel: {{
                        color: '#c8d6e5',
                        fontSize: 11,
                        formatter: function (val) {{ return val.toFixed(2); }}
                    }},
                    splitLine: {{ show: true, lineStyle: {{ color: '#161a25' }} }}
                }},
                {{
                    type: 'value',
                    gridIndex: 1,
                    scale: true,
                    position: 'right',
                    axisLine: {{ lineStyle: {{ color: '#222736' }} }},
                    axisLabel: {{
                        color: '#8c9ba5',
                        fontSize: 9,
                        formatter: function (val) {{
                            if (val >= 1e8) return (val / 1e8).toFixed(1) + '亿';
                            if (val >= 1e4) return (val / 1e4).toFixed(0) + '万';
                            return val;
                        }}
                    }},
                    splitLine: {{ show: true, lineStyle: {{ color: '#161a25' }} }}
                }}
            ],
            dataZoom: [
                {{
                    type: 'inside',
                    xAxisIndex: [0, 1],
                    start: {init_start_pct},
                    end: {init_end_pct}
                }},
                {{
                    show: true,
                    xAxisIndex: [0, 1],
                    type: 'slider',
                    top: '91%',
                    height: 20,
                    backgroundColor: '#121622',
                    fillerColor: 'rgba(52, 73, 94, 0.45)',
                    borderColor: '#1e2433',
                    textStyle: {{ color: '#8c9ba5', fontSize: 10 }},
                    start: {init_start_pct},
                    end: {init_end_pct}
                }}
            ],
            series: [
                {{
                    name: 'K线',
                    type: 'candlestick',
                    data: klineValues,
                    itemStyle: {{
                        color: UP_COLOR,
                        color0: DOWN_COLOR,
                        borderColor: UP_COLOR,
                        borderColor0: DOWN_COLOR
                    }},
                    markPoint: {{
                        data: chartData.markPoints,
                        symbolSize: 22
                    }},
                    markLine: {{
                        symbol: ['circle', 'arrow'],
                        symbolSize: [3, 5],
                        data: chartData.markLines,
                        label: {{
                            show: true,
                            position: 'middle',
                            formatter: '{{b}}',
                            fontSize: 10,
                            color: '#f1f2f6'
                        }}
                    }}
                }},
                {{
                    name: 'MA5',
                    type: 'line',
                    data: chartData.ma5,
                    smooth: true,
                    showSymbol: false,
                    lineStyle: {{ color: '#fadb14', width: 1.1, opacity: 0.9 }}
                }},
                {{
                    name: 'MA10',
                    type: 'line',
                    data: chartData.ma10,
                    smooth: true,
                    showSymbol: false,
                    lineStyle: {{ color: '#e056fd', width: 1.1, opacity: 0.9 }}
                }},
                {{
                    name: 'MA20',
                    type: 'line',
                    data: chartData.ma20,
                    smooth: true,
                    showSymbol: false,
                    lineStyle: {{ color: '#00d2d3', width: 1.2, opacity: 0.9 }}
                }},
                {{
                    name: 'MA60',
                    type: 'line',
                    data: chartData.ma60,
                    smooth: true,
                    showSymbol: false,
                    lineStyle: {{ color: '#ffffff', width: 1.2, opacity: 0.9 }}
                }},
                {{
                    name: '成交量',
                    type: 'bar',
                    xAxisIndex: 1,
                    yAxisIndex: 1,
                    data: chartData.volumes.map(function(item) {{
                        return {{
                            value: item[1],
                            itemStyle: {{ color: item[2] === 1 ? UP_COLOR : DOWN_COLOR }}
                        }};
                    }})
                }},
                {{
                    name: 'VOL5',
                    type: 'line',
                    xAxisIndex: 1,
                    yAxisIndex: 1,
                    data: chartData.vma5,
                    smooth: true,
                    showSymbol: false,
                    lineStyle: {{ color: '#fadb14', width: 1.0 }}
                }},
                {{
                    name: 'VOL10',
                    type: 'line',
                    xAxisIndex: 1,
                    yAxisIndex: 1,
                    data: chartData.vma10,
                    smooth: true,
                    showSymbol: false,
                    lineStyle: {{ color: '#e056fd', width: 1.0 }}
                }}
            ]
        }};

        myChart.setOption(option);
        window.addEventListener('resize', function() {{
            myChart.resize();
        }});

        // 点击图表上的买卖点，自动触发放大该笔交割
        myChart.on('click', function(params) {{
            if (params.componentType === 'markPoint' && params.data && params.data.tradeIdx !== undefined) {{
                const tIdx = params.data.tradeIdx;
                document.getElementById('tradeFocusSelect').value = tIdx;
                focusTrade(tIdx);
            }}
        }});

        function focusTrade(val) {{
            const alertDom = document.getElementById('focusAlertText');
            if (val === 'all') {{
                myChart.dispatchAction({{
                    type: 'dataZoom',
                    start: 0,
                    end: 100
                }});
                if (alertDom) alertDom.style.display = 'none';
                return;
            }}
            const tIdx = parseInt(val);
            if (isNaN(tIdx) || tIdx < 0 || tIdx >= tradesList.length) return;
            const trade = tradesList[tIdx];
            const bDate = trade.buyDate;
            const sDate = trade.sellDate;
            const bIdx = dates.indexOf(bDate);
            const sIdx = dates.indexOf(sDate);
            if (bIdx === -1) return;
            const endTargetIdx = (sIdx !== -1) ? sIdx : dates.length - 1;

            // 向前取 12 日缓冲，向后取 15 日缓冲
            const startI = Math.max(0, bIdx - 12);
            const endI = Math.min(dates.length - 1, endTargetIdx + 15);
            const startPct = Math.max(0, (startI / totalCount) * 100);
            const endPct = Math.min(100, (endI / totalCount) * 100);

            myChart.dispatchAction({{
                type: 'dataZoom',
                start: startPct,
                end: endPct
            }});

            if (alertDom) {{
                alertDom.style.display = 'inline-block';
                alertDom.innerText = `🔍 已聚焦单笔交割: 第 ${{tIdx+1}} 笔 [${{bDate}} ➜ ${{sDate}}] 收益: ${{trade.pnl}} (持仓 ${{trade.holdDays}} 天)`;
            }}

            const btns = document.querySelectorAll('.ths-btn');
            btns.forEach(b => b.classList.remove('active'));
        }}

        function zoomRange(days) {{
            let start = 0;
            if (days !== 'all' && totalCount > days) {{
                start = Math.max(0, Math.floor(((totalCount - days) / totalCount) * 100));
            }}
            myChart.dispatchAction({{
                type: 'dataZoom',
                start: start,
                end: 100
            }});
            const alertDom = document.getElementById('focusAlertText');
            if (alertDom) alertDom.style.display = 'none';
            document.getElementById('tradeFocusSelect').value = 'all';

            const btns = document.querySelectorAll('.ths-btn');
            btns.forEach(b => b.classList.remove('active'));
            event.target.classList.add('active');
        }}
    </script>
</body>
</html>
"""
    return html_content
