#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股全市场全量数据同步与 Qlib 二进制引擎构建脚本
数据源: Sina / AkShare (免费、高效、覆盖 2005 至今全部历史及今日 2026-10-09)
标的范围: 沪、深、京全部 5,500+ 只 A 股及核心基准指数 (SH000300, SH000905 等)
"""

import os
import sys
import time
import shutil
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import numpy as np
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("SyncAllAShares")

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))
DATA_DIR = WORKSPACE_DIR / "data"
CSV_RAW_DIR = DATA_DIR / "csv_raw"
QLIB_DATA_DIR = DATA_DIR / "cn_data"
QLIB_BACKUP_DIR = DATA_DIR / "cn_data_backup"
STOCK_CODES_FILE = DATA_DIR / "all_stock_codes.csv"

TODAY_STR = "2026-10-09"
START_DATE_STR = "2005-01-01"

BENCHMARK_INDICES = [
    ("sh000300", "SH000300"),  # 沪深300
    ("sh000905", "SH000905"),  # 中证500
    ("sh000001", "SH000001"),  # 上证指数
    ("sz399001", "SZ399001"),  # 深证成指
    ("sz399006", "SZ399006"),  # 创业板指
    ("sh000688", "SH000688"),  # 科创50
]

def ensure_stock_codes():
    """确保全市场股票代码列表存在"""
    if STOCK_CODES_FILE.exists():
        df = pd.read_csv(STOCK_CODES_FILE)
        logger.info(f"已加载本地全市场代码列表: {len(df)} 只股票")
        return df

    import akshare as ak
    logger.info("正在从交易所抓取全市场股票代码列表...")
    sh_main = ak.stock_info_sh_name_code("主板A股")[["证券代码", "证券简称"]]
    sh_kcb = ak.stock_info_sh_name_code("科创板")[["证券代码", "证券简称"]]
    sz = ak.stock_info_sz_name_code("A股列表")[["A股代码", "A股简称"]]
    sz.columns = ["证券代码", "证券简称"]
    sz["证券代码"] = sz["证券代码"].astype(str).str.zfill(6)
    bj = ak.stock_info_bj_name_code()[["证券代码", "证券简称"]]
    bj["证券代码"] = bj["证券代码"].astype(str).str.zfill(6)

    df = pd.concat([sh_main, sh_kcb, sz, bj], ignore_index=True)
    df = df.drop_duplicates(subset=["证券代码"])
    df.columns = ["code", "name"]
    df.to_csv(STOCK_CODES_FILE, index=False)
    logger.info(f"成功保存 {len(df)} 只股票至 {STOCK_CODES_FILE}")
    return df

def fetch_single_stock(code: str) -> bool:
    """抓取单只股票的前复权历史日线至今日并存为标准 CSV"""
    import akshare as ak

    # 确定市场前缀 (北交所 920/8/4 必须优先判断，避免 920 被误判为沪市 9 开头)
    if code.startswith("920") or code.startswith("8") or code.startswith("4"):
        prefix_lower, prefix_upper = "bj", "BJ"
    elif code.startswith("6") or code.startswith("9"):
        prefix_lower, prefix_upper = "sh", "SH"
    else:
        prefix_lower, prefix_upper = "sz", "SZ"

    std_symbol = f"{prefix_upper}{code}"
    csv_path = CSV_RAW_DIR / f"{std_symbol}.csv"

    # 断点续传检查：若文件存在且最后一条记录包含今日或昨日期，则跳过
    if csv_path.exists() and csv_path.stat().st_size > 200:
        try:
            with open(csv_path, "rb") as f:
                f.seek(max(0, csv_path.stat().st_size - 300))
                tail = f.read().decode("utf-8", errors="ignore")
                if "2026-10-09" in tail or "2026-10-08" in tail:
                    return True
        except Exception:
            pass

    ak_symbol = f"{prefix_lower}{code}"
    max_retries = 3
    for attempt in range(max_retries):
        try:
            df = ak.stock_zh_a_daily(
                symbol=ak_symbol,
                start_date="20050101",
                end_date="20261009",
                adjust="qfq"
            )
            if df is None or len(df) == 0:
                return False

            # 标准化列名
            df = df.rename(columns={"amount": "money"})
            df["factor"] = 1.0
            df["adjclose"] = df["close"]
            df["change"] = (df["close"] / df["close"].shift(1) - 1.0).fillna(0.0)
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

            cols = ["date", "open", "high", "low", "close", "volume", "money", "factor", "adjclose", "change"]
            # 过滤需要的列并丢弃空行
            out_df = df[cols].dropna(subset=["date", "close"])
            if len(out_df) == 0:
                return False

            out_df.to_csv(csv_path, index=False)
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
            else:
                return False
    return False

def fetch_single_index(ak_symbol: str, std_symbol: str) -> bool:
    """抓取核心基准指数日线"""
    import akshare as ak
    csv_path = CSV_RAW_DIR / f"{std_symbol}.csv"
    try:
        df = ak.stock_zh_index_daily(symbol=ak_symbol)
        if df is None or len(df) == 0:
            return False
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["factor"] = 1.0
        df["money"] = df.get("amount", df["volume"] * df["close"])
        df["adjclose"] = df["close"]
        df["change"] = (df["close"] / df["close"].shift(1) - 1.0).fillna(0.0)

        cols = ["date", "open", "high", "low", "close", "volume", "money", "factor", "adjclose", "change"]
        out_df = df[cols].dropna(subset=["date", "close"])
        out_df = out_df[out_df["date"] >= "2005-01-01"]
        out_df.to_csv(csv_path, index=False)
        logger.info(f"基准指数 {std_symbol} 抓取成功 ({len(out_df)} 条记录，截止: {out_df.iloc[-1]['date']})")
        return True
    except Exception as e:
        logger.warning(f"基准指数 {std_symbol} 抓取失败: {e}")
        return False

def download_all_stocks(codes: list, max_workers: int = 16):
    """多线程并行拉取所有股票日线"""
    CSV_RAW_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"[*] 开始并行抓取全市场日线行情 (目标标的: {len(codes)} 只，并发线程: {max_workers})...")

    # 首先抓取基准指数
    for ak_sym, std_sym in BENCHMARK_INDICES:
        fetch_single_index(ak_sym, std_sym)

    success_cnt = 0
    fail_cnt = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(fetch_single_stock, code): code for code in codes}
        with tqdm(total=len(codes), desc="同步 A 股行情", unit="标的") as pbar:
            for future in as_completed(future_map):
                ok = future.result()
                if ok:
                    success_cnt += 1
                else:
                    fail_cnt += 1
                pbar.update(1)

    logger.info(f"[✓] 历史行情抓取完成: 成功 {success_cnt} 只，无数据/失败 {fail_cnt} 只")

def build_instruments_pool():
    """拉取并生成 CSI300, CSI500 成分股文件"""
    import akshare as ak
    inst_dir = QLIB_DATA_DIR / "instruments"
    inst_dir.mkdir(parents=True, exist_ok=True)

    pools = [
        ("000300", "csi300.txt"),
        ("000905", "csi500.txt")
    ]

    for index_code, filename in pools:
        try:
            df_cons = ak.index_stock_cons(symbol=index_code)
            if df_cons is not None and len(df_cons) > 0:
                lines = []
                for _, row in df_cons.iterrows():
                    code = str(row["品种代码"]).zfill(6)
                    prefix = "SH" if code.startswith("6") or code.startswith("9") else "SZ"
                    symbol = f"{prefix}{code}"
                    start_dt = str(row.get("纳入日期", "2005-01-01"))[:10]
                    lines.append(f"{symbol}\t{start_dt}\t{TODAY_STR}")
                target_file = inst_dir / filename
                with open(target_file, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
                logger.info(f"[✓] 生成成分股文件 {filename}: {len(lines)} 只标的")
        except Exception as e:
            logger.warning(f"获取指数 {index_code} 成分股失败: {e}")

def dump_to_qlib_binary():
    """调用 dump_bin.py 将 CSV 转换为 Qlib 专属二进制格式"""
    logger.info("[*] 开始转换为 Qlib 二进制格式 (calendars, instruments, features)...")

    # 备份原有 cn_data
    if QLIB_DATA_DIR.exists() and not QLIB_BACKUP_DIR.exists():
        logger.info(f"[*] 备份原有数据至 {QLIB_BACKUP_DIR}...")
        shutil.copytree(QLIB_DATA_DIR, QLIB_BACKUP_DIR)

    from scripts.dump_bin import DumpDataAll

    dump_all = DumpDataAll(
        data_path=str(CSV_RAW_DIR),
        qlib_dir=str(QLIB_DATA_DIR),
        max_workers=8,
        include_fields="open,close,high,low,volume,money,factor,adjclose,change"
    )
    dump_all.dump()
    logger.info("[✓] Qlib 二进制特征与基础日历转换完成")

    # 生成 day_future.txt (向未来延伸 1 年日历，供 Qlib 回测与因子滑窗预测对齐使用)
    cal_file = QLIB_DATA_DIR / "calendars" / "day.txt"
    cal_future_file = QLIB_DATA_DIR / "calendars" / "day_future.txt"
    if cal_file.exists():
        with open(cal_file, "r", encoding="utf-8") as f:
            days = [line.strip() for line in f if line.strip()]
        last_day = pd.Timestamp(days[-1])
        # 生成未来 365 天工作日
        future_range = pd.bdate_range(start=last_day + pd.Timedelta(days=1), periods=250)
        future_days = [d.strftime("%Y-%m-%d") for d in future_range]
        all_future_days = days + future_days
        with open(cal_future_file, "w", encoding="utf-8") as f:
            f.write("\n".join(all_future_days) + "\n")
        logger.info(f"[✓] 生成未来交易日历 day_future.txt ({len(all_future_days)} 天)")

    # 重新构建成分股名单
    build_instruments_pool()

def verify_qlib_data():
    """验证 Qlib 引擎对新数据的读取"""
    import qlib
    from qlib.data import D

    logger.info("[*] 验证 Qlib 本地数据源...")
    qlib.init(provider_uri=str(QLIB_DATA_DIR), region="cn")

    # 检查标的
    inst_all = D.list_instruments(instruments=D.instruments(market="all"), as_list=True)
    logger.info(f"[✓] Qlib 可检索标的总数: {len(inst_all)} 只")

    # 抽样读取最新行情
    sample_stocks = ["SH600519", "SZ000001", "SH000300"]
    available_samples = [s for s in sample_stocks if s in inst_all]

    for s in available_samples:
        df = D.features([s], fields=["$open", "$close", "$volume", "$money"], start_time="2026-09-25", end_time=TODAY_STR)
        logger.info(f"\n标的 {s} 最新走势数据 (至 {TODAY_STR}):\n{df.tail(3)}")

    logger.info("\n🎉 全市场 A 股数据已成功同步至最新时间！")

def main():
    stock_df = ensure_stock_codes()
    codes = stock_df["code"].astype(str).str.zfill(6).tolist()

    # 1. 抓取日线
    download_all_stocks(codes, max_workers=16)

    # 2. 转为二进制
    dump_to_qlib_binary()

    # 3. 校验
    verify_qlib_data()

if __name__ == "__main__":
    main()
