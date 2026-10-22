#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股 ETF 实时快照行情适配器
支持批量抓取毫秒级实时价格、买一卖一价、行情时间、涨跌幅与质量校验
"""

import time
import datetime
from zoneinfo import ZoneInfo
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
    now = datetime.datetime.now(ZoneInfo("Asia/Shanghai"))

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
                quote_dt = datetime.datetime.strptime(f"{q_date} {q_time}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                age_seconds = int((now - quote_dt).total_seconds())
            except Exception:
                quote_dt = None
                age_seconds = None

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
        print(f"[-] 新浪实时行情失败，切换腾讯备用源: {e}")

    # 新浪接口在部分网络环境下会超时；腾讯接口字段稳定，作为同一时点的备用源。
    if not results:
        try:
            backup = session.get(
                "https://qt.gtimg.cn/q=" + ",".join(formatted_codes),
                headers={"Referer": "https://gu.qq.com"}, timeout=5,
            )
            backup.raise_for_status()
            for line in backup.text.split(";"):
                if '="' not in line:
                    continue
                left, right = line.split('="', 1)
                code = left.replace("v_", "").strip().lower()
                parts = right.rstrip('"').split("~")
                if len(parts) < 31 or not parts[3]:
                    continue
                price = float(parts[3])
                prev_close = float(parts[4]) if parts[4] else price
                quote_raw = parts[30]
                quote_dt = datetime.datetime.strptime(quote_raw, "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                results[code] = {
                    "symbol": code, "name": parts[1], "price": price,
                    "prev_close": prev_close, "open": float(parts[5] or price),
                    "high": float(parts[33] or price) if len(parts) > 33 else price,
                    "low": float(parts[34] or price) if len(parts) > 34 else price,
                    "bid1": float(parts[9] or price), "ask1": float(parts[19] or price),
                    "quote_time": quote_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "quote_dt": quote_dt, "age_seconds": int((now - quote_dt).total_seconds()),
                    "chg_pct": ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0,
                    "is_trading": price > 0,
                }
        except Exception as backup_error:
            print(f"[-] 腾讯实时行情也失败: {backup_error}")

    return results

if __name__ == "__main__":
    quotes = fetch_realtime_quotes(["sz159915", "sh512890"])
    for sym, q in quotes.items():
        print(f"[{sym}] {q['name']}: ¥{q['price']:.3f} ({q['chg_pct']:+.2f}%) 行情时间: {q['quote_time']} (延迟 {q['age_seconds']} 秒)")
