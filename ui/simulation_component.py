"""Approved Demo frontend connected to the existing transactional paper-account service."""
import math
import sqlite3
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from services.simulation_store import AccountError, SimulationStore, now
from services.simulation_service import ASSETS, build_plan, execute_plan, market_status, sellable, symbols_for
from services.simulation_runtime import ensure_worker, worker_alive
from ui.simulation_data import live_quotes, cached_signal, refresh_quotes

FRONTEND = Path(__file__).parent / 'simulation_frontend'
workspace_component = components.declare_component('quant_simulation_workspace', path=str(FRONTEND.resolve()))
RESEARCH = {'模拟账户', '红利高抛低吸', '攻守轮动', '复合攻守轮动', '因子实验', '模型回测'}


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, 'item'):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def frontend_config(account):
    p = account['parameters']
    if account['strategy_type'] == 'compound_rotation':
        return dict(
            attack=p.get('tech_symbol', 'sz159915'),
            divDefense=p.get('div_symbol', 'sh512890'),
            bondDefense=p.get('bond_symbol', p.get('def_symbol', 'sh511260')),
            lookback=p.get('lookback_window', 20),
            executionMode=p.get('execution_mode', 'next_open'),
            useBias=p.get('use_bias_exit', True),
            useTrend=p.get('use_trend_filter', True),
            overheat=p.get('th_overheat', 0.20) * 100,
            neutral=p.get('th_neutral', 0.35) * 100,
        )
    if account['strategy_type'] == 'rotation':
        return dict(attack=p['tech_symbol'], defense=p['def_symbol'], lookback=p['lookback_window'])
    return dict(executionMode=p.get('execution_mode','tail'), defense=p.get('defensive_asset', 'cash'), low=p['threshold_low']*100, high=p['threshold_high']*100,
                lowWeight=p['weight_low']*100, midWeight=p['weight_mid']*100, highWeight=p['weight_high']*100)


def backend_config(action):
    c = action['config']
    if action['strategy'] == 'compound':
        return 'compound_rotation', dict(
            tech_symbol=c['attack'],
            div_symbol=c.get('divDefense', 'sh512890'),
            bond_symbol=c.get('bondDefense', 'sh511260'),
            lookback_window=int(c['lookback']),
            execution_mode=c.get('executionMode', 'next_open'),
            use_bias_exit=bool(c.get('useBias', True)),
            use_trend_filter=bool(c.get('useTrend', True)),
            th_overheat=float(c.get('overheat', 20)) / 100.0,
            th_neutral=float(c.get('neutral', 35)) / 100.0,
        )
    if action['strategy'] == 'rotation':
        return 'rotation', dict(tech_symbol=c['attack'], def_symbol=c['defense'], lookback_window=int(c['lookback']))
    if action['strategy'] != 'erp':
        raise AccountError('请选择已支持的策略。')
    return 'dividend_erp', dict(execution_mode=c.get('executionMode','tail'), defensive_asset=c.get('defense', 'cash'), threshold_low=c['low']/100, threshold_high=c['high']/100,
                               weight_low=c['lowWeight']/100, weight_mid=c['midWeight']/100, weight_high=c['highWeight']/100)


def snapshot(store, selected=None):
    accounts = store.list_accounts()
    symbols = tuple(sorted({s for a in accounts for s in symbols_for(a)}))
    quotes = live_quotes(symbols)
    # 行情源短暂超时可能把空结果缓存 15 秒；首次拿不到报价时立即走一次备用源重试。
    if symbols and any(not quotes.get(s, {}).get('price') for s in symbols):
        refresh_quotes()
        quotes = live_quotes(symbols)
    rows = []
    for a in accounts:
        prices = tuple((s, quotes.get(s, {}).get('price')) for s in symbols_for(a))
        sig = cached_signal(a['strategy_type'], a['parameters'], prices, now().date().isoformat()) if all(p and p > 0 for _, p in prices) else {'valid': False, 'error': '所需行情不完整，请刷新后重试。'}
        p = build_plan(store, a['id'], quotes=quotes, signal=sig)
        sig = p['signal']
        observation = None
        if a['strategy_type'] in ('dividend_erp', 'compound_rotation'):
            def observation_signal(mode):
                if not all(price and price > 0 for _, price in prices):
                    return {'valid': False, 'error': '行情不完整，暂无法计算。'}
                return cached_signal(a['strategy_type'], {**a['parameters'], 'execution_mode': mode}, prices, now().date().isoformat())
            ref_sym = a['parameters'].get('tech_symbol', 'sz159915') if a['strategy_type'] == 'compound_rotation' else 'sh512890'
            observation = dict(live=observation_signal('tail'), confirmed=observation_signal('next_open'),
                               quoteTime=quotes.get(ref_sym, {}).get('quote_time', '未知'))
        port = p['portfolio']
        positions = [{**v, 'sellable': sellable(v, now().date().isoformat())} for v in port['positions']]
        def records(kind):
            return [{**r, 'time': r['timestamp'].replace('T', ' ')[:19]} for r in store.entries(a['id'], kind)]
        rows.append(dict(id=a['id'], name=a['name'], revision=a['revision'], strategy='erp' if a['strategy_type']=='dividend_erp' else ('compound' if a['strategy_type']=='compound_rotation' else 'rotation'),
                         config=frontend_config(a), initial=a['initial_capital'], netCapital=a['net_capital'], cash=a['cash_available'],
                         auto=a['auto_trade'], running=a['running'], feeRate=a['fee_rate'], created=a['created_at'][:10],
                         observation=observation, positions=positions, portfolio=port, legacyOpening=store.legacy_opening_snapshot(a), trades=records('trade'), funds=records('fund'), events=records('event'),
                         plan=dict(id=p['id'], orders=p['orders'], fees=p['fees'], remaining=p['remaining_cash'], error=p['error'], signal=sig,
                                   canExecute=p['can_execute'], reasons=p['reasons'], quoteTimes=p['quote_times'],
                                   target=dict(symbol=sig['target_symbol'] if sig else '', weight=sig['weight']*100 if sig else None),
                                   insufficient=any('不足一手' in r for r in p['reasons']))))
    selected_account = next((a for a in accounts if a["id"] == selected), accounts[0] if accounts else None)
    market = market_status(mode=selected_account["parameters"].get("execution_mode", "tail") if selected_account else "tail")
    market.update(full=f"{now():%Y-%m-%d} · {market['label']}", time=f'{now():%H:%M:%S}')
    return clean(dict(accounts=rows, selected=selected or (rows[0]['id'] if rows else None),
                      assets={s: {'name': ASSETS.get(s, s), 'price': quotes.get(s, {}).get('price'), 'prevClose': quotes.get(s, {}).get('prev_close'), 'chgPct': quotes.get(s, {}).get('chg_pct'), 'quoteTime': quotes.get(s, {}).get('quote_time')} for s in set(ASSETS)|set(symbols)},
                      market=market, worker={'alive': worker_alive(store), 'pipeline': store.metadata('pipeline') or {}}))


def dispatch(store, action):
    """Accept user intent only; never trust client balances, quotes, signals or fills."""
    kind = action['action']
    account_id = action.get('accountId')
    response = dict(requestId=action['requestId'], action=kind, ok=True, silent=bool(action.get('silent')), accountId=account_id)
    if kind in ('create', 'configure'):
        strategy, parameters = backend_config(action)
        if kind == 'create':
            a = store.create(action['name'], action['capital'], strategy, parameters, auto=action['auto'], fee_rate=action['feeRate'])
            response.update(accountId=a['id'], message='账户已创建，核对调仓清单即可开始。')
        else:
            store.configure(account_id, action['revision'], action['name'], strategy, parameters, action['auto'], action['feeRate'])
            response['message'] = '设置已保存，调仓清单已重新生成。'
        ensure_worker(store)
    elif kind == 'funds':
        store.transfer(account_id, action['revision'], action['amount'], action['withdraw'], request_id='component-fund:'+action['requestId'])
        response['message'] = '资金操作已完成，现金与流水已更新。'
    elif kind == 'pause':
        store.set_running(account_id, action['revision'], action['running'])
        ensure_worker(store)
        response['message'] = '账户已恢复运行。' if action['running'] else '账户已暂停，配置与持仓已保留。'
    elif kind == 'execute':
        result = execute_plan(store, account_id, action['planId'], 'manual:'+action['planId'])
        response['message'] = result['message']
        refresh_quotes()
    elif kind == 'refresh':
        if not action.get('silent'):
            refresh_quotes()
        response['message'] = '行情与清单已刷新。'
    elif kind == 'select':
        store.get(account_id)
    elif kind == 'navigate':
        if action.get('mode') not in RESEARCH:
            raise AccountError('未知研究入口。')
        response['navigate'] = action['mode']
    else:
        raise AccountError('不支持的账户操作。')
    return response


HOST_CSS = '''<style>
.stApp:has(.st-key-simulation_frontend_host) [data-testid="stSidebar"],
.stApp:has(.st-key-simulation_frontend_host) [data-testid="stHeader"]{display:none!important}
.stApp:has(.st-key-simulation_frontend_host) [data-testid="stMainBlockContainer"]{max-width:none!important;padding:0!important;height:100dvh!important}
.stApp:has(.st-key-simulation_frontend_host) [data-testid="stMain"]{overflow:hidden!important}
.st-key-simulation_frontend_host iframe{height:100dvh!important;width:100%!important;border:0;display:block}
.st-key-simulation_frontend_host{height:100dvh!important;gap:0!important}
.stApp:has(.st-key-simulation_frontend_host) [data-testid="stMainBlockContainer"]>[data-testid="stVerticalBlock"]{gap:0!important}
.stApp:has(.st-key-simulation_frontend_host) [data-testid="stMainBlockContainer"]>[data-testid="stVerticalBlock"]>[data-testid="stElementContainer"]:has(style){display:none!important}
</style>'''


def render_simulation_workspace():
    st.html(HOST_CSS)
    with st.container(key='simulation_frontend_host'):
        try:
            store = SimulationStore()
            ensure_worker(store)
            data = snapshot(store, st.session_state.get('simulation_selected'))
        except (AccountError, sqlite3.Error, OSError, ValueError) as exc:
            st.error(f'账户数据暂不可用：{exc}')
            return
        action = workspace_component(snapshot=data, response=st.session_state.get('simulation_component_response'), key='connected_workspace', default=None)
        handled = st.session_state.setdefault('simulation_component_handled', [])
        if not action or not isinstance(action, dict) or not action.get('requestId') or action['requestId'] in handled:
            return
        handled.append(action['requestId'])
        del handled[:-200]
        try:
            response = dispatch(store, action)
            if response.get('accountId'):
                st.session_state['simulation_selected'] = response['accountId']
            if response.get('navigate'):
                st.session_state['simulation_route'] = response['navigate']
        except (AccountError, sqlite3.Error, OSError, KeyError, TypeError, ValueError) as exc:
            response = dict(requestId=action['requestId'], action=action.get('action'), ok=False, message=str(exc) or '操作失败，请刷新后重试。')
        st.session_state['simulation_component_response'] = response
        st.rerun()
