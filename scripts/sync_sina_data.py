#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新浪财经 A 股最新行情同步脚本
获取沪深300核心成份股及指数最新日线 (至 2026-10-09)
"""

import os
import sys
sys.path.append(".")
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from data.sina_fetcher import fetch_sina_stock_kline

# 沪深300主要代表性股票池 (跨行业核心龙头)
CORE_STOCKS = [
    "sh600519", "sz000858", "sh601318", "sz000001", "sh600036", "sz002594",
    "sh601012", "sz300750", "sh600276", "sz002475", "sh601888", "sz002714",
    "sh600030", "sh601166", "sh600900", "sz000333", "sh601899", "sz300059",
    "sh600887", "sz002415", "sh600028", "sh601857", "sh601988", "sz000651",
    "sh600104", "sz002142", "sh601668", "sz000725", "sh600436", "sz002352",
    "sh600309", "sh601398", "sh601288", "sh601939", "sh600000", "sh600016"
]

BENCHMARK_SYMBOL = "sh000300"

def sync_all_core_data():
    print(f"[*] 开始从新浪财经同步 {len(CORE_STOCKS)} 只核心标的最新行情 (至 2026-10-09)...")
    
    # 同步基准沪深300
    fetch_sina_stock_kline(BENCHMARK_SYMBOL, datalen=1024)
    
    success = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_sina_stock_kline, s, 1024): s for s in CORE_STOCKS}
        for f in futures:
            try:
                df = f.result()
                if len(df) > 0:
                    success += 1
            except Exception as e:
                pass
                
    print(f"[✓] 新浪财经同步完成！成功缓存 {success}/{len(CORE_STOCKS)} 只标的最新日线至 ./data/sina_cache")

if __name__ == "__main__":
    sync_all_core_data()
