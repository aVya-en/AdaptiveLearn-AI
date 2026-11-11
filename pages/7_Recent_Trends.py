"""Student-scoped recent quiz trend detail report."""

from time import perf_counter as _perf_counter

_page_started = _perf_counter()

import sqlite3

import streamlit as st

from database.learning_data import get_learning_data_snapshot
from modules.learning_profile import build_learning_profile
from ui.components import render_empty_state, render_kicker
from ui.theme import THEME
from utils.auth_ui import require_student
from utils.performance import finish_page_timer
from utils.streamlit_ui import render_static_table
from utils.performance import measure_stage

_page_timer = ("progress_trends", _page_started)
st.set_page_config(page_title="Recent Trends | AdaptiveLearn AI", page_icon="📈", layout="wide")
def _build_trend_chart_spec(values: list[dict[str, object]]) -> dict[str, object]:
    """Build the line, nearest-point hover, and zoom behavior without Altair conversion."""
    encoding = {
        "tooltip": [
            {"field": "Completed", "type": "nominal"},
            {"field": "Score", "type": "quantitative"},
        ],
        "x": {
            "axis": {"grid": False}, "field": "Completed", "scale": {},
            "title": "Completion date", "type": "nominal",
        },
        "y": {
            "axis": {"grid": True, "tickMinStep": 1}, "field": "Score", "scale": {},
            "title": "Score (%)", "type": "quantitative",
        },
    }
    return {
        "data": {"values": values},
        "layer": [
            {
                "name": "view_1",
                "mark": {"type": "line", "color": THEME["chart-accent"]},
                "encoding": encoding,
            },
            {"name": "view_2", "mark": {"type": "point", "opacity": 0}, "encoding": encoding},
            {
                "mark": {
                    "type": "point", "filled": True, "size": 65,
                    "color": THEME["chart-accent"],
                },
                "encoding": encoding,
                "transform": [{"filter": {"param": "recent_score_hover", "empty": False}}],
            },
        ],
        "params": [
            {
                "name": "recent_score_hover",
                "select": {
                    "type": "point", "clear": "mouseleave", "fields": ["Completed"],
                    "nearest": True, "on": "mousemove",
                },
                "views": ["view_2"],
            },
            {
                "name": "recent_score_zoom",
                "select": {"type": "interval", "encodings": ["x", "y"]},
                "bind": "scales",
                "views": ["view_1"],
            },
        ],
        "config": {
            "axis": {
                "labelColor": THEME["label"],
                "titleColor": THEME["label"],
                "gridColor": THEME["chart-grid"],
                "tickColor": THEME["control-border"],
                "domainColor": THEME["control-border"],
            },
            "background": THEME["surface"],
            "legend": {"symbolType": "stroke", "labelColor": THEME["label"], "titleColor": THEME["label"]},
            "view": {"stroke": "transparent"},
        },
    }


student = require_student()

if st.button("← Back to Progress", key="progress-trends-back"):
    st.switch_page("pages/4_Progress.py")
render_kicker("Your learning evidence")
st.title("Recent Trends")
st.markdown(
    '<p class="al-page-description">Compare saved quiz scores over time and review the recent-versus-earlier performance trend.</p>',
    unsafe_allow_html=True,
)

try:
    snapshot = get_learning_data_snapshot(int(student["id"]))
    profile = build_learning_profile(snapshot)
except sqlite3.Error as error:
    st.error(f"Could not load your recent trends: {error}")
else:
    subjects = profile["subjects"]
    if not subjects:
        render_empty_state(
            "No quiz history yet",
            "Complete a quiz to build a subject-specific performance history.",
        )
    else:
        subject_names = [item["subject"] for item in subjects]
        if st.session_state.get("progress_subject") not in subject_names:
            st.session_state["progress_subject"] = subject_names[0]
        selected_subject = st.selectbox(
            "Explore Subject", subject_names, key="progress_subject"
        )
        selected = next(item for item in subjects if item["subject"] == selected_subject)
        st.caption(f"Selected subject · {selected_subject}")

        trend = selected["recent_performance_trend"]
        trend_ready = trend["direction"] != "insufficient_history"
        metrics = st.columns(4, gap="small")
        metric_values = (
            ("Recent average", f"{trend['recent_average_score']:.1f}%" if trend["recent_average_score"] is not None else "Unavailable"),
            ("Earlier average", f"{trend['previous_average_score']:.1f}%" if trend["previous_average_score"] is not None else "Unavailable"),
            ("Change", f"{trend['change_percentage_points']:+.1f} pp" if trend["change_percentage_points"] is not None else "Unavailable"),
            ("Direction", trend["direction"].replace("_", " ").title()),
        )
        for column, (label, value) in zip(metrics, metric_values):
            with column:
                st.metric(label, value)

        attempts = [
            dict(row) for row in snapshot["recent_attempts"]
            if row["subject"] == selected_subject
        ]
        if not trend_ready:
            render_empty_state(
                "Not enough quiz history yet",
                "A trend comparison needs saved attempts in both the recent and earlier windows. Available attempt scores are shown below without assigning a direction.",
            )
        if attempts:
            with measure_stage("recent_trends.data_transform", provider="local", task="render"):
                chronological = sorted(
                    attempts, key=lambda row: (str(row["completed_at"]), int(row["id"]))
                )
                chart_data = [
                    {"Completed": row["completed_at"], "Score": float(row["score"])}
                    for row in chronological
                ]
                chart_spec = _build_trend_chart_spec(chart_data)
                recent_table_rows = [
                    (row["topic"], row["difficulty"], f"{float(row['score']):.1f}%", row["completed_at"])
                    for row in reversed(chronological)
                ]
            st.markdown("### Saved quiz scores")
            with measure_stage("ui.chart_construction", provider="local", task="render"):
                st.vega_lite_chart(chart_spec, width="stretch", height=300)
            st.caption("Showing up to 10 most recent saved attempts for this subject.")
            render_static_table(
                ["Topic", "Difficulty", "Score", "Completed"],
                recent_table_rows,
            )
        else:
            render_empty_state(
                "No quiz attempts for this subject",
                "Saved quiz results will appear here when they are available.",
            )

finish_page_timer(_page_timer)
