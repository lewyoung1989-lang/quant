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
    parser.add_argument('--profile-dir')
    args=parser.parse_args()
    if args.resource:
        print(json.dumps(update_resource(args.resource,args.day),ensure_ascii=False))
        return
    store=SimulationStore(args.profile_dir)
    with (store.directory/'daily_pipeline.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        request=store.metadata('pipeline_sync_request') or {}
        manual=request.get('status') in ('待处理', '同步中')
        if manual:
            store.metadata('pipeline_sync_request', {**request, 'status':'同步中'})
        else:
            from services.simulation_runtime import ensure_worker
            ensure_worker(store)
        try:
            result=tick(store, force=manual)
        except Exception as exc:
            from services.simulation_store import now
            state=store.metadata('pipeline') or {}
            state.update(ready=False, status='任务异常', message=str(exc), heartbeat=now().isoformat())
            store.metadata('pipeline', state)
            raise
        finally:
            if manual and (store.metadata('pipeline_sync_request') or {}).get('id') == request['id']:
                state=store.metadata('pipeline') or {}
                store.metadata('pipeline_sync_request', {**request, 'status':'已完成' if state.get('ready') else '等待重试'})
        print(json.dumps(result,ensure_ascii=False,default=str))

if __name__=='__main__':main()
