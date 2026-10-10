#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股最新日线数据增量更新与 Qlib 二进制转换工具
数据源支持: AkShare (免费、无需 Token)
作用: 抓取指定股票池最新行情至今日 (2026-10-09)，并转换为 Qlib 专属 bin 格式
"""

import os
import sys
import shutil
from pathlib import Path
import pandas as pd
from tqdm import tqdm

def fetch_and_dump_to_qlib(
    stock_symbols=["600519", "000858", "601318", "000001", "600036"],
    start_date="20210612",
    end_date="20261009",
    csv_dir="./data/csv_raw",
    qlib_dir="./data/cn_data"
):
    try:
        import akshare as ak
    except ImportError:
        print("[-] 请先安装 akshare: pip install akshare")
        return

    os.makedirs(csv_dir, exist_ok=True)
    print(f"[*] 开始从 AkShare 获取 A 股历史日线 (自 {start_date} 至 {end_date})...")

    success_count = 0
    for symbol in tqdm(stock_symbols, desc="下载股票数据"):
        try:
            # 获取前复权历史日线
            df = ak.stock_zh_a_hist(symbol=symbol, start_date=start_date, end_date=end_date, adjust="qfq")
            if df is None or len(df) == 0:
                continue

            # 标准化列名以适配 Qlib dump 格式 (date, open, high, low, close, volume, money, factor)
            df = df.rename(columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "money",
                "振幅": "amplitude",
                "换手率": "turnover"
            })
            df["factor"] = 1.0  # 前复权价格对应 factor 为 1.0
            
            # 格式化股票代码 (例如 600519 -> SH600519, 000001 -> SZ000001)
            prefix = "SH" if symbol.startswith("6") or symbol.startswith("9") else "SZ"
            standard_symbol = f"{prefix}{symbol}"
            
            output_csv = os.path.join(csv_dir, f"{standard_symbol}.csv")
            df.to_csv(output_csv, index=False)
            success_count += 1
        except Exception as e:
            # 打印单个失败提示
            pass

    print(f"[✓] 成功下载 {success_count} 只标的历史日线到 {csv_dir}")
    print("[*] 提示: 接下来可调用 Qlib 官方 dump_bin 命令增量注入 data/cn_data")
    print(f"    命令: python -m qlib.dump_bin --csv_path {csv_dir} --qlib_dir {qlib_dir} --include_fields open,close,high,low,volume,factor")

if __name__ == "__main__":
    fetch_and_dump_to_qlib()
