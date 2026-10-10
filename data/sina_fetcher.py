#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新浪财经 A 股历史日线与实时行情抓取模块
支持直连抓取最新至 2026-10-09 的历史日线数据 (OHLCV)
"""

import os
import time
import requests
import pandas as pd
from pathlib import Path

CACHE_DIR = Path("./data/sina_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def fetch_tencent_stock_kline(symbol="sz159915", start_date="2011-01-01", end_date="2026-10-10"):
    """
    通过腾讯财经接口分页获取完整超长历史 K 线 (支持从 2011 年甚至更早至最新)
    """
    code = symbol.lower()
    s = requests.Session()
    s.trust_env = False
    headers = {"User-Agent": "Mozilla/5.0"}
    
    all_klines = []
    curr_end = end_date
    
    for _ in range(15): # 最多向前翻页 15 次，足够覆盖 15 年以上
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,{start_date},{curr_end},640,qfq"
        try:
            res = s.get(url, headers=headers, timeout=10)
            res.raise_for_status()
            data = res.json()
            if not isinstance(data.get("data"), dict) or code not in data["data"]:
                break
            items = data["data"][code].get("qfqday", data["data"][code].get("day"))
            if not items:
                break
            # 拼接并去重
            all_klines = items + [x for x in all_klines if x[0] > items[-1][0]]
            first_day = items[0][0]
            if first_day <= start_date or first_day == curr_end:
                break
            curr_end = first_day
        except Exception as e:
            print(f"[-] 抓取腾讯历史行情出错 {code}: {e}")
            break
            
    if not all_klines:
        return pd.DataFrame()
        
    records = []
    for item in all_klines:
        records.append({
            "datetime": item[0],
            "open": float(item[1]),
            "close": float(item[2]),
            "high": float(item[3]),
            "low": float(item[4]),
            "volume": float(item[5])
        })
    df = pd.DataFrame(records).set_index("datetime")
    df.index = pd.to_datetime(df.index)
    df.sort_index(inplace=True)
    return df

def fetch_sina_stock_kline(symbol="sh600519", datalen=1024, start_date=None):
    """
    抓取指定股票的历史日K线。
    若需要超过 1000 天或指定较早 start_date（如 2013 年），自动采用长周期接口获取全量数据。
    :param symbol: 如 'sh600519' 或 'sz159915'
    :param datalen: 获取最大交易日天数
    :return: DataFrame [datetime, open, high, low, close, volume]
    """
    code = symbol.lower()
    if not (code.startswith("sh") or code.startswith("sz")):
        code = ("sh" if code.startswith("6") or code.startswith("9") else "sz") + code

    cache_file = CACHE_DIR / f"{code}.csv"
    
    # 检查本地缓存
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < 3600 * 24:
        df = pd.read_csv(cache_file, index_col="datetime", parse_dates=True)
        # 如果缓存覆盖范围已包含需要的时间或条数，直接返回
        if len(df) >= datalen or (start_date and df.index.min() <= pd.to_datetime(start_date)):
            return df

    # 如果请求较长历史（>1000天 或 start_date <= 2021），优先尝试全量接口
    if datalen > 1000 or (start_date and str(start_date) < "2022-01-01"):
        try:
            s_d = str(start_date) if start_date else "2011-01-01"
            long_df = fetch_tencent_stock_kline(code, start_date=s_d)
            if len(long_df) > 0:
                long_df.to_csv(cache_file)
                return long_df
        except Exception as e:
            print(f"[-] 抓取全量长历史失败，降级至标准接口: {e}")

    s = requests.Session()
    s.trust_env = False
    headers = {"Referer": "https://finance.sina.com.cn"}
    
    url = f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol={code}&scale=240&ma=no&datalen={min(datalen, 1024)}"
    
    try:
        res = s.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        if not data:
            return pd.DataFrame()
            
        records = []
        for item in data:
            records.append({
                "datetime": item["day"],
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": float(item["volume"])
            })
            
        df = pd.DataFrame(records).set_index("datetime")
        df.index = pd.to_datetime(df.index)
        df.sort_index(inplace=True)
        df.to_csv(cache_file)
        return df
    except Exception as e:
        print(f"[-] 获取 {symbol} 行情失败: {e}")
        if cache_file.exists():
            return pd.read_csv(cache_file, index_col="datetime", parse_dates=True)
        return pd.DataFrame()

if __name__ == "__main__":
    df = fetch_sina_stock_kline("sz159915", datalen=3000, start_date="2013-01-01")
    print(f"[✓] 数据测试成功: 共 {len(df)} 根K线, 起始: {df.index.min()}, 截止: {df.index.max()}")
    print(df.head(2))
    print(df.tail(2))
