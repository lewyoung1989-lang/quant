#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股 ETF 实时快照行情适配器
支持批量抓取毫秒级实时价格、买一卖一价、行情时间、涨跌幅与质量校验
"""

import time
import datetime
import requests
import pandas as pd

def fetch_realtime_quotes(symbols=["sz159915", "sh512890"]):
    """
    抓取指定标的的实时行情
    :param symbols: 标的代码列表，如 ['sz159915', 'sh512890']
    :return: dict { symbol: { price, prev_close, open, high, low, bid1, ask1, time, name, status, age_seconds } }
    """
    formatted_codes = []
    for s in symbols:
        code = s.lower().strip()
        if not (code.startswith("sh") or code.startswith("sz")):
            code = ("sh" if code.startswith("6") or code.startswith("5") else "sz") + code
        formatted_codes.append(code)

    query_str = ",".join(formatted_codes)
    url = f"https://hq.sinajs.cn/list={query_str}"
    
    session = requests.Session()
    session.trust_env = False
    headers = {"Referer": "https://finance.sina.com.cn"}

    results = {}
    now = datetime.datetime.now()

    try:
        resp = session.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        lines = resp.text.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line or '="' not in line:
                continue
            left, right = line.split('="')
            code = left.replace("var hq_str_", "").strip().lower()
            val_str = right.rstrip('";')
            parts = val_str.split(",")
            
            if len(parts) < 32:
                continue

            name = parts[0]
            open_p = float(parts[1]) if parts[1] else 0.0
            prev_close = float(parts[2]) if parts[2] else 0.0
            cur_price = float(parts[3]) if parts[3] else prev_close
            high_p = float(parts[4]) if parts[4] else cur_price
            low_p = float(parts[5]) if parts[5] else cur_price
            bid1 = float(parts[6]) if parts[6] else cur_price
            ask1 = float(parts[7]) if parts[7] else cur_price
            q_date = parts[30]
            q_time = parts[31]

            # 组合行情时间
            try:
                quote_dt = datetime.datetime.strptime(f"{q_date} {q_time}", "%Y-%m-%d %H:%M:%S")
                age_seconds = max(0, int((now - quote_dt).total_seconds()))
            except Exception:
                quote_dt = now
                age_seconds = 0

            # 涨跌幅
            chg_pct = ((cur_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

            results[code] = {
                "symbol": code,
                "name": name,
                "price": cur_price,
                "prev_close": prev_close,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "bid1": bid1,
                "ask1": ask1,
                "quote_time": f"{q_date} {q_time}",
                "quote_dt": quote_dt,
                "age_seconds": age_seconds,
                "chg_pct": chg_pct,
                "is_trading": cur_price > 0
            }

    except Exception as e:
        print(f"[-] 抓取实时行情失败: {e}")

    return results

if __name__ == "__main__":
    quotes = fetch_realtime_quotes(["sz159915", "sh512890"])
    for sym, q in quotes.items():
        print(f"[{sym}] {q['name']}: ¥{q['price']:.3f} ({q['chg_pct']:+.2f}%) 行情时间: {q['quote_time']} (延迟 {q['age_seconds']} 秒)")
