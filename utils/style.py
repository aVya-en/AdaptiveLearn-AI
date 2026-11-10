"""Shared visual styling for the Streamlit application and page files."""

import streamlit as st

from ui.styles import GLOBAL_CSS
from utils.performance import measure_function


@measure_function("ui.apply_app_style")
def apply_app_style() -> None:
    """Apply shared dark workspace styles across all application pages."""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
