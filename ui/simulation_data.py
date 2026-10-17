"""Read-only quote and signal caches shared by the connected simulation workspace."""
import datetime as dt

import streamlit as st

from services.simulation_service import fetch_quotes, local_time, strategy_signal


@st.cache_data(ttl=15, show_spinner=False)
def live_quotes(symbols):
    return fetch_quotes(list(symbols))


@st.cache_data(ttl=30, max_entries=40, show_spinner=False)
def cached_signal(strategy, parameters, prices, day):
    account = {'strategy_type': strategy, 'parameters': parameters}
    try:
        return strategy_signal(account, {s: {'price': p} for s, p in prices}, local_time(dt.datetime.fromisoformat(day + 'T14:50:00')))
    except Exception as exc:
        return {'valid': False, 'error': str(exc) or '策略信号计算失败，请更新数据后重试。'}


def refresh_quotes():
    live_quotes.clear()
    cached_signal.clear()
