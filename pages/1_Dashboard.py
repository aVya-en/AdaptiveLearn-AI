from time import perf_counter as _perf_counter

_page_started = _perf_counter()

import streamlit as st

from modules.dashboard import render_dashboard
from utils.auth_ui import require_student
from utils.style import apply_app_style
from utils.performance import finish_page_timer

_page_timer = ("dashboard", _page_started)
st.set_page_config(page_title="Dashboard | AdaptiveLearn AI", page_icon="\U0001F4CA", layout="wide")
apply_app_style()
student = require_student()
render_dashboard(student)
finish_page_timer(_page_timer)
