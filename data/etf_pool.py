#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主流 A 股指数与大类资产 ETF 标的池配置
"""

import sys
sys.path.append(".")
ETF_POOL = {
    "sh510300": "沪深300ETF (大盘蓝筹)",
    "sh510500": "中证500ETF (中盘成长)",
    "sz159915": "创业板ETF (高成长创新)",
    "sh588000": "科创50ETF (硬科技龙头)",
    "sh588380": "双创50ETF (科创创业50)",
    "sh512100": "中证1000ETF (小盘成长)",
    "sh512890": "红利低波ETF (稳健高股息)",
    "sh518880": "黄金ETF (大类避险资产)",
    "sh511010": "国债ETF (现金避险管理)",
    "sh511260": "十年国债ETF (中长端避险基准)",
    "sh511090": "三十年国债ETF (超长端进攻防守债)",
    "sh513100": "纳斯达克ETF (全球科技配置)"
}

def sync_etf_data():
    from data.sina_fetcher import fetch_sina_stock_kline
    print(f"[*] 开始同步 {len(ETF_POOL)} 只核心指数 ETF 数据 (至 2026-10-09)...")
    for code, name in ETF_POOL.items():
        df = fetch_sina_stock_kline(code, datalen=1024)
        print(f"  [✓] {name} ({code}): {len(df)} 交易日, 最新: {df.index.max().strftime('%Y-%m-%d')}")

if __name__ == "__main__":
    sync_etf_data()
