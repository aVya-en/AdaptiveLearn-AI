"""AdaptiveLearn AI native multipage entry point."""

from time import perf_counter as _perf_counter

_page_started = _perf_counter()

import sqlite3

import streamlit as st

from database.db import initialize_database
from utils.config import load_configuration
from utils.performance import finish_page_timer

load_configuration()
st.set_page_config(page_title="AdaptiveLearn AI", page_icon="📘", layout="wide")
st.set_option("client.toolbarMode", "minimal")

try:
    initialize_database()
except sqlite3.Error as error:
    st.error(f"Could not initialize the local database: {error}")
    st.stop()

is_authenticated = bool(st.session_state.get("student"))
visibility = "visible" if is_authenticated else "hidden"
navigation_pages = {
    "LEARN": [
        st.Page("pages/1_Dashboard.py", title="Dashboard", icon=":material/dashboard:", default=is_authenticated, visibility=visibility),
        st.Page("pages/5_Learning_Path.py", title="Learning Path", icon=":material/route:", visibility=visibility),
        st.Page("pages/3_Practice.py", title="Practice", icon=":material/edit_note:", visibility=visibility),
        st.Page("pages/2_AI_Tutor.py", title="AI Tutor", icon=":material/forum:", visibility=visibility),
        st.Page("pages/4_Progress.py", title="Progress", icon=":material/monitoring:", visibility=visibility),
        st.Page(
            "pages/6_Concept_Performance.py", title="Concept Performance",
            icon=":material/analytics:", url_path="concept-performance", visibility="hidden",
        ),
        st.Page(
            "pages/7_Recent_Trends.py", title="Recent Trends",
            icon=":material/trending_up:", url_path="recent-trends", visibility="hidden",
        ),
    ],
    "ACCOUNT": [
        st.Page(
            "pages/0_Sign_In.py",
            title="Sign in",
            icon=":material/person:",
            default=not is_authenticated,
            visibility="hidden" if is_authenticated else "visible",
        ),
    ],
}

if is_authenticated:
    with st.sidebar:
        with st.container(key="adaptivelearn-sidebar-brand"):
            st.markdown(
                '<div class="adaptivelearn-brand"><div class="adaptivelearn-brand-icon">✦</div>'
                '<div><strong>AdaptiveLearn AI</strong><small>AI-powered learning workspace</small></div></div>',
                unsafe_allow_html=True,
            )

page = st.navigation(navigation_pages, position="sidebar" if is_authenticated else "hidden", expanded=True)
page.run()
finish_page_timer(("entrypoint", _page_started))
