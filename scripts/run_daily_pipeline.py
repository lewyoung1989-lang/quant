#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.simulation_store import SimulationStore
from services.daily_pipeline import tick, update_resource


def main():
    parser=argparse.ArgumentParser(description='每日数据补齐及策略预生成，失败自动重试。')
    parser.add_argument('--resource')
    parser.add_argument('--day')
    args=parser.parse_args()
    if args.resource:
        print(json.dumps(update_resource(args.resource,args.day),ensure_ascii=False))
        return
    store=SimulationStore()
    with (store.directory/'daily_pipeline.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        from services.simulation_runtime import ensure_worker
        ensure_worker(store)
        try:
            result=tick(store)
        except Exception as exc:
            from services.simulation_store import now
            state=store.metadata('pipeline') or {}
            state.update(ready=False, status='任务异常', message=str(exc), heartbeat=now().isoformat())
            store.metadata('pipeline', state)
            raise
        print(json.dumps(result,ensure_ascii=False,default=str))

if __name__=='__main__':main()
