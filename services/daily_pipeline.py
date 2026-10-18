"""Durable catch-up jobs. All times are exchange-local, all writes are atomic."""
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import pandas as pd
from services.simulation_store import ROOT, now
from services.simulation_service import is_session, previous_session, fetch_quotes, strategy_signal, symbols_for


def target_day(at):
    if is_session(at.date()) is None:
        raise ValueError('交易日历缺失，请更新年度交易日历。')
    return at.date().isoformat() if is_session(at.date()) and at.time().replace(tzinfo=None) >= dt.time(16, 30) else previous_session(at.date())


def atomic_csv(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        frame.to_csv(tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def update_resource(resource, day):
    """Called in a bounded subprocess, so a stalled provider cannot hang scheduling."""
    if resource.startswith('price:'):
        symbol = resource.split(':')[1]
        from data.sina_fetcher import fetch_tencent_stock_kline
        frame = fetch_tencent_stock_kline(symbol, end_date=day)
        path = ROOT / 'data/sina_cache' / (symbol+'.csv')
        required = ['open', 'high', 'low', 'close']
    elif resource == 'valuation':
        import akshare as ak
        frame = ak.stock_zh_index_hist_csindex(symbol='H30269', start_date='20190101', end_date=day.replace('-',''))
        frame['日期'] = pd.to_datetime(frame['日期'])
        frame = frame.set_index('日期')
        path = ROOT / 'data/h30269_index_hist.csv'
        required = ['滚动市盈率']
    elif resource == 'rates':
        import akshare as ak
        frame = ak.bond_zh_us_rate()
        frame['日期'] = pd.to_datetime(frame['日期'])
        frame = frame.set_index('日期')
        path = ROOT / 'data/bond_rates_hist.csv'
        required = ['中国国债收益率10年']
    else:
        raise ValueError('未知数据任务')
    frame.index = pd.to_datetime(frame.index)
    frame = frame[~frame.index.duplicated(keep='last')].sort_index()
    frame = frame.loc[frame.index <= pd.Timestamp(day)].dropna(subset=required)
    if frame.empty or frame.index[-1].date().isoformat() != day:
        raise ValueError(f'{resource} 尚未发布或未取得 {day} 完整数据')
    if resource != 'rates' and (frame[required] <= 0).any().any():
        raise ValueError('价格或估值出现非正数')
    # A fresh complete series avoids mixing differently adjusted price histories.
    if resource.startswith('price:') and len(frame) < 260:
        raise ValueError('完整历史不足 260 日，保留旧快照')
    if path.exists() and resource.startswith('price:'):
        old = pd.read_csv(path, index_col=0, parse_dates=True)
        if len(old) and frame.index.min() > old.index.min():
            raise ValueError('新行情截短历史，保留旧快照并重试')
    atomic_csv(frame, path)
    if resource.startswith('price:'):
        marker = path.with_suffix('.ready.json')
        tmp = marker.with_suffix('.tmp')
        tmp.write_text(json.dumps({'asof':day}))
        os.replace(tmp, marker)
    if resource == 'price:sh512890':
        atomic_csv(frame, ROOT / 'data/sh512890_kline.csv')
    return {'asof': day, 'rows': len(frame), 'source': 'Tencent' if resource.startswith('price:') else 'AkShare', 'updated_at': now().isoformat()}


def run_resource(resource, day):
    result = subprocess.run([sys.executable, str(ROOT/'scripts/run_daily_pipeline.py'), '--resource', resource, '--day', day], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-1200:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def tick(store, at=None, updater=run_resource):
    at = at or now()
    stamp = at.isoformat()
    state = store.metadata('pipeline') or {}
    try:
        day = target_day(at)
        if not day:
            raise ValueError('无法确定最近完整交易日')
    except ValueError as exc:
        state.update(status='数据待更新', message=str(exc), heartbeat=stamp, ready=False)
        store.metadata('pipeline', state)
        return state
    accounts = store.list_accounts()
    symbols = {'sh512890','sh511260','sh000300'} | {s for a in accounts for s in symbols_for(a)}
    resources = ['price:'+s for s in sorted(symbols)] + ['valuation','rates']
    jobs = state.get('jobs', {})
    state.update(target=day, heartbeat=stamp, ready=False, status='检查数据', jobs=jobs)
    store.metadata('pipeline', state)
    for resource in resources:
        job = jobs.get(resource, {})
        if job.get('asof') == day and job.get('status') == '成功':
            continue
        retry = job.get('retry_after')
        if retry and retry > stamp and job.get('target') == day:
            continue
        jobs[resource] = {**job, 'status':'更新中', 'target':day, 'started_at':stamp}
        store.metadata('pipeline', state)
        try:
            jobs[resource] = {**updater(resource, day), 'status':'成功', 'target':day}
        except Exception as exc:
            jobs[resource] = {**job, 'status':'等待重试', 'target':day, 'error':str(exc)[-600:], 'retry_after':(at+dt.timedelta(minutes=15)).isoformat()}
        store.metadata('pipeline', state)
    ready = all(jobs.get(r,{}).get('asof') == day and jobs[r].get('status') == '成功' for r in resources)
    state.update(ready=ready, status='数据已就绪' if ready else '数据待更新',
                 message=f'数据截至 {day}' if ready else f'尚有数据未覆盖 {day}，15 分钟后重试；暂停调仓。', heartbeat=now().isoformat())
    store.metadata('pipeline', state)
    if ready:
        signature = hashlib.sha256(json.dumps([(a['id'], a['settings_version'], a['parameters']) for a in accounts], sort_keys=True).encode()).hexdigest()
        last = state.get('signals_at')
        market_hours = is_session(at.date()) and dt.time(9,15) <= at.time().replace(tzinfo=None) <= dt.time(15,5)
        due = not last or state.get('signals_signature') != signature or state.get('signals_target') != day
        if market_hours and last:
            due = due or (at-dt.datetime.fromisoformat(last)).total_seconds() >= 300
        if due:
            try:
                quotes = fetch_quotes(sorted(symbols))
            except Exception as exc:
                state.update(signals={a['id']: {'status': '失败', 'error': str(exc), 'generated_at': stamp} for a in accounts},
                             signals_signature=None, signals_at=stamp)
                store.metadata('pipeline', state)
                return state
            signal_at = at if day < at.date().isoformat() else at + dt.timedelta(days=1)
            signals = {}
            for a in accounts:
                try:
                    sig = strategy_signal(a, quotes, signal_at)
                    # Pandas indicators can contain NumPy scalar booleans/numbers.
                    sig = json.loads(json.dumps(sig, default=lambda v: v.item() if hasattr(v, 'item') else str(v)))
                    if not sig.get('valid') or sig.get('historical_asof') != day:
                        raise ValueError('信号历史日期未对齐')
                    signals[a['id']] = {'parameters':a['parameters'], 'settings_version':a['settings_version'], 'generated_at':stamp, 'data_asof':day, 'signal':sig, 'status':'成功'}
                except Exception as exc:
                    signals[a['id']] = {'status':'失败', 'error':str(exc), 'generated_at':stamp}
            state.update(signals=signals, signals_at=stamp, signals_signature=signature, signals_target=day)
            if any(v['status']!='成功' for v in signals.values()):
                # Keep retrying on the next tick even outside market hours.
                state['signals_signature'] = None
            store.metadata('pipeline', state)
            store.metadata('signals:'+stamp, signals)
    return state
