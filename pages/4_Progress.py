"""Student-scoped progress overview and links to detailed reports."""

from time import perf_counter as _perf_counter

_page_started = _perf_counter()

import streamlit as st

from database.db import DATABASE_ERRORS
from database.learning_data import get_learning_data_snapshot
from modules.learning_profile import build_learning_profile
from ui.components import render_empty_state, render_kicker
from utils.auth_ui import require_student
from utils.performance import finish_page_timer, measure_stage
from utils.streamlit_ui import render_static_table

_page_timer = ("progress", _page_started)
st.set_page_config(page_title="Progress | AdaptiveLearn AI", page_icon="📈", layout="wide")
student = require_student()

render_kicker("Evidence from your practice")
st.title("Progress")
st.markdown(
    '<p class="al-page-description">A concise view of your subject performance, with details when you need them.</p>',
    unsafe_allow_html=True,
)


def _trend_label(trend: dict[str, object] | None) -> str:
    if not trend or trend.get("direction") == "insufficient_history":
        return "Not enough history"
    return str(trend["direction"]).replace("_", " ").title()


try:
    with measure_stage("progress.data_preparation", provider="local", task="render"):
        snapshot = get_learning_data_snapshot(int(student["id"]))
        profile = build_learning_profile(snapshot)
        recent_attempts = sorted(
            snapshot["recent_attempts"],
            key=lambda row: (str(row["completed_at"]), int(row["id"])),
            reverse=True,
        )[:5]
except DATABASE_ERRORS as error:
    st.error(f"Could not load your progress: {error}")
else:
    subjects = profile["subjects"]
    subject_names = [item["subject"] for item in subjects]
    selected = None
    selected_subject = None

    with st.container(border=True, key="progress-overview-card"):
        title_column, subject_column = st.columns([3, 1], gap="medium")
        with title_column:
            st.markdown("### Student overview")
        with subject_column:
            if subject_names:
                if st.session_state.get("progress_subject") not in subject_names:
                    st.session_state["progress_subject"] = subject_names[0]
                selected_subject = st.selectbox(
                    "Explore Subject", subject_names, key="progress_subject"
                )
                selected = next(item for item in subjects if item["subject"] == selected_subject)
            else:
                st.selectbox(
                    "Explore Subject", ["No subject data yet"],
                    key="progress_subject_unavailable", disabled=True,
                )

        metrics = st.columns(4, gap="small")
        if selected:
            accuracy = selected["overall_accuracy"]
            trend_label = _trend_label(selected["recent_performance_trend"])
            metric_values = (
                ("Subject accuracy", f"{accuracy:.1f}%" if accuracy is not None else "Unavailable"),
                ("Questions attempted", str(selected["total_questions_attempted"])),
                ("Concepts tracked", str(selected["concepts_assessed"])),
                ("Recent performance", trend_label),
            )
        else:
            metric_values = tuple(
                (label, "Unavailable")
                for label in ("Subject accuracy", "Questions attempted", "Concepts tracked", "Recent performance")
            )
        for column, (label, value) in zip(metrics, metric_values):
            with column:
                st.metric(label, value)
        if selected:
            trend = selected["recent_performance_trend"]
            if trend["direction"] == "insufficient_history":
                st.caption("Not enough quiz history yet to compare recent and earlier performance.")
            elif trend["recent_average_score"] is not None:
                st.caption(
                    f"Recent average {trend['recent_average_score']:.1f}% · "
                    f"earlier average {trend['previous_average_score']:.1f}%"
                )
        else:
            st.caption("Complete a quiz to build your student-specific progress overview.")

    st.subheader("Explore details")
    if selected:
        concepts = selected["concept_performance"]
        counts = {
            category: sum(item["assessment"] == category for item in concepts)
            for category in ("strong", "developing", "weak", "insufficiently_assessed")
        }
        trend = selected["recent_performance_trend"]
        classified_count = sum(counts[key] for key in ("strong", "developing", "weak"))
        if concepts:
            concept_summary = (
                f"<div class=\"al-progress-tile-stat\"><strong>{len(concepts)}</strong> concepts tracked</div>"
                f"<div class=\"al-progress-tile-counts\">"
                f"<span>{counts['strong']} strong</span><span>{counts['developing']} developing</span>"
                f"<span>{counts['weak']} weak</span></div>"
            )
            if not classified_count:
                concept_summary += '<div class="al-progress-tile-empty">No concepts classified yet</div>'
        else:
            concept_summary = '<div class="al-progress-tile-empty">No concepts classified yet</div>'

        if trend["direction"] == "insufficient_history":
            trend_status = "Insufficient history"
            trend_summary = '<div class="al-progress-tile-empty">Not enough history yet</div>'
        else:
            trend_status = trend["direction"].replace("_", " ").title()
            delta = trend.get("change_percentage_points")
            if delta is None:
                recent = trend.get("recent_average_score")
                previous = trend.get("previous_average_score")
                delta = recent - previous if recent is not None and previous is not None else None
            trend_summary = (
                f'<div class="al-progress-tile-stat">{trend["recent_average_score"]:.1f}% recent '
                f'vs {trend["previous_average_score"]:.1f}% earlier</div>'
            )
            if delta is not None:
                trend_summary += f'<div class="al-progress-tile-change">{delta:+.1f} percentage points</div>'
    else:
        concept_summary = '<div class="al-progress-tile-empty">No concepts classified yet</div>'
        trend_status = "Insufficient history"
        trend_summary = '<div class="al-progress-tile-empty">Not enough history yet</div>'

    def render_progress_tile(*, key: str, title: str, description: str, summary: str, button_label: str) -> bool:
        with st.container(key=key):
            st.markdown(
                '<div class="al-progress-tile-content">'
                f'<div class="al-progress-tile-heading">{title}</div>'
                f'<div class="al-progress-tile-description">{description}</div>'
                f'<div class="al-progress-tile-summary">{summary}</div>'
                '<div class="al-progress-tile-footer">View details →</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            return st.button(button_label, key=f"{key}-button", use_container_width=True)

    with st.container(key="progress-detail-grid"):
        concept_column, trend_column = st.columns(2, gap="medium", vertical_alignment="top")
        with concept_column:
            if render_progress_tile(
                key="progress-concept-tile", title="Concept Performance",
                description="See how well you understand individual concepts.",
                summary=concept_summary, button_label="Open Concept Performance details",
            ):
                st.switch_page("pages/6_Concept_Performance.py")
        with trend_column:
            if render_progress_tile(
                key="progress-trends-tile", title="Recent Trends",
                description="Compare your recent performance with earlier attempts.",
                summary=(
                    f'<div class="al-progress-tile-status">{trend_status}</div>{trend_summary}'
                ), button_label="Open Recent Trends details",
            ):
                st.switch_page("pages/7_Recent_Trends.py")

    st.subheader("Recent Quiz History")
    attempts = [
        row for row in recent_attempts
        if selected_subject is not None and row["subject"] == selected_subject
    ]
    if attempts:
        render_static_table(
            ["Topic", "Difficulty", "Questions", "Score", "Completed"],
            [
                (row["topic"], row["difficulty"], row["total_questions"],
                 f"{row['score']:.1f}%", row["completed_at"])
                for row in attempts
            ],
        )
    else:
        render_empty_state(
            "No quiz attempts yet",
            "Completed quizzes for the selected subject will appear here.",
        )

finish_page_timer(_page_timer)
