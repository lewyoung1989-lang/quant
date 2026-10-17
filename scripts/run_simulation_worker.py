#!/usr/bin/env python3
"""Run paper execution independently of Streamlit: python scripts/run_simulation_worker.py."""
import argparse
import logging
import os
import fcntl
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.simulation_service import worker_tick
from services.simulation_store import SimulationStore, timestamp


def main():
    parser = argparse.ArgumentParser(description="交易日尾盘自动模拟调仓；不连接券商。")
    parser.add_argument("--profile-dir", help="本地账户数据目录，默认 data/user_profile")
    parser.add_argument("--interval", type=int, default=20, help="检查间隔（秒），最小 5 秒")
    parser.add_argument("--once", action="store_true", help="只检查一次，适用于外部调度")
    args = parser.parse_args()
    store = SimulationStore(args.profile_dir)
    lock = (store.directory / "simulation_worker.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return 0
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        while True:
            try:
                result = worker_tick(store)
                result["pid"] = os.getpid()
                store.metadata("worker", result)
                logging.info("%s", result["message"])
            except Exception:
                logging.exception("自动模拟检查失败")
                store.metadata("worker", {"heartbeat": timestamp(), "status": "异常", "message": "自动检查失败，请查看运行日志。"})
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(max(5, args.interval))
    except KeyboardInterrupt:
        store.metadata("worker", {"heartbeat": timestamp(), "status": "已停止", "message": "后台检查已停止。"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
