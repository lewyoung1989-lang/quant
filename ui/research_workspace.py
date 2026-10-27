"""Research pages share the approved workspace navigation and visual tokens."""
from pathlib import Path
import html
import streamlit as st
from ui.simulation_component import workspace_component, RESEARCH
from ui.data_sync import prepare_research_data, render_data_sync


def render_research_shell(mode):
    prepare_research_data(mode)
    st.html('<style>' + Path(__file__).with_suffix('.css').read_text() + '</style>')
    with st.sidebar:
        action = workspace_component(navigationOnly=True, mode=mode, key='research_navigation', default=None)
    if isinstance(action, dict) and action.get('requestId') != st.session_state.get('research_navigation_handled'):
        st.session_state['research_navigation_handled'] = action.get('requestId')
        if action.get('mode') in RESEARCH:
            st.session_state['simulation_route'] = action['mode']
            st.rerun()
    st.markdown(f'<div class="research-topbar"><span>策略研究 <span class="slash">/</span> <b>{html.escape(mode)}</b></span><span class="research-environment">模拟交易环境</span></div>', unsafe_allow_html=True)
    render_data_sync()
