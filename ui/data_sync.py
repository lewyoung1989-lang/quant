"""Shared historical-data controls for research pages; real-time quotes stay separate."""
import html

import streamlit as st

from services.daily_pipeline import request_sync, sync_status
from services.simulation_store import SimulationStore
from ui.research_preferences import ResearchPreferences


def prepare_research_data(mode):
    state = sync_status(SimulationStore())
    ResearchPreferences(mode).apply_data_sync(state.get('data_asof'), state.get('completed_at'))
    st.session_state.setdefault('research_data_revision', state.get('completed_at'))


@st.fragment(run_every=3)
def render_data_sync():
    store = SimulationStore()
    state = sync_status(store)
    revision = state.get('completed_at')
    if revision != st.session_state.get('research_data_revision'):
        st.session_state['research_data_revision'] = revision
        st.rerun()
    busy = state['syncing']
    info, control = st.columns([4, 1.3], vertical_alignment='center')
    with info:
        asof = state.get('data_asof')
        label = f'回测数据截至 {asof}' if asof else '回测历史数据待同步'
        schedule = state.get('schedule', '交易日 20:10')
        st.markdown(f'<div class="research-data-status"><b>{html.escape(label)}</b><span>{schedule} 自动同步</span></div>', unsafe_allow_html=True)
        st.caption('正在同步历史日线、指数估值与国债利率…' if busy else state.get('message', '同步后，回测结束日期更新至最新完整交易日。'))
    with control:
        if st.button('正在同步…' if busy else '同步回测数据', disabled=busy, width='stretch',
                     help='下载历史日线、指数估值和国债利率，完成后更新回测结束日期。盘中截至前一交易日；收盘后同步当天数据。'):
            try:
                st.toast(request_sync(store))
            except OSError as exc:
                st.error(f'同步未能启动：{exc}')
            st.rerun(scope='fragment')
