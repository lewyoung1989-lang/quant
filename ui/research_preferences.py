"""Local, per-strategy research preferences, independent of Streamlit sessions."""
from contextlib import contextmanager
import datetime as dt
import hashlib
import inspect
import json
import os
import sqlite3
from pathlib import Path
import streamlit as st


@contextmanager
def database():
    root = Path(os.environ.get('QUANT_PROFILE_DIR', str(Path(__file__).resolve().parents[1] / 'data/user_profile')))
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / 'research_preferences.sqlite3', timeout=10)
    conn.execute('CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def encode(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return {'date': value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()}
    raise TypeError(type(value).__name__)


def read(key, default=None):
    with database() as conn:
        row = conn.execute('SELECT value FROM preferences WHERE key=?', (key,)).fetchone()
    try:
        return json.loads(row[0], object_hook=lambda v: dt.date.fromisoformat(v['date']) if set(v)=={'date'} else v) if row else default
    except (ValueError, TypeError):
        return default


def write(key, value):
    with database() as conn:
        conn.execute('INSERT INTO preferences VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (key, json.dumps(value, default=encode, ensure_ascii=False)))


class ResearchPreferences:
    def __init__(self, strategy):
        self.strategy = strategy

    def apply_data_sync(self, day, revision):
        """Advance only the end date once per successful historical-data revision."""
        if not day or not revision:
            return
        marker = 'research_data_sync_' + self.strategy
        identity = [self.strategy, 'date_input', '结束日期', None, None, None]
        key = 'research_' + hashlib.sha256(repr(identity).encode()).hexdigest()[:24]
        if read(marker) != revision:
            write(key, dt.date.fromisoformat(day))
            write(marker, revision)
        if st.session_state.get(marker) != revision:
            st.session_state[key] = read(key)
            st.session_state[marker] = revision

    def __getattr__(self, kind):
        widget = getattr(st, kind)

        def render(*args, **kwargs):
            params = dict(inspect.signature(widget).bind(*args, **kwargs).arguments)
            # Different option sets/ranges keep independent values (e.g. ETF vs stock Top-K).
            identity = [self.strategy, kind, params['label'], params.get('min_value'), params.get('max_value'), params.get('options')]
            key = 'research_' + hashlib.sha256(repr(identity).encode()).hexdigest()[:24]
            saved = read(key)
            if saved is not None:
                if kind in ('selectbox', 'radio'):
                    options = list(params['options'])
                    if saved in options:
                        params['index'] = options.index(saved)
                elif kind == 'date_input':
                    params['value'] = tuple(saved) if isinstance(saved, list) else saved
                elif kind in ('slider', 'number_input'):
                    if isinstance(saved, (int,float)) and (params.get('min_value') is None or saved >= params['min_value']) and (params.get('max_value') is None or saved <= params['max_value']):
                        params['value'] = saved
                elif isinstance(saved, str):
                    params['value'] = saved
            params['key'] = key
            def changed():
                try:
                    write(key, st.session_state[key])
                except (OSError, sqlite3.Error) as exc:
                    st.error(f'参数保存失败：{exc}')
            params['on_change'] = changed
            return widget(**params)
        return render
