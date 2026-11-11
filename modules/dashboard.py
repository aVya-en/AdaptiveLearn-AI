"""Student dashboard presentation backed only by saved learning records."""

import sqlite3

import streamlit as st

from database.learning_data import get_cached_dashboard_overview
from ui.components import render_kicker
from utils.performance import measure_function, measure_stage


SUBJECT_CARDS = (
    ("DSA", "Data Structures and Algorithms", "Core problem-solving patterns and complexity."),
    ("Python", "Python Programming", "Build fluency with clear, practical code."),
    ("DBMS", "Database Management Systems", "Understand relational data and SQL."),
)
GENERAL_STARTING_POINTS = (
    ("DSA", "Arrays and strings", "Practice the building blocks of problem solving."),
    ("Python", "Variables and data types", "Build a foundation for writing programs."),
    ("DBMS", "Relational model", "Explore how relational data is organized."),
)


def _start_practice(student_id: int, subject: str, topic: str | None = None) -> None:
    """Hand off to the existing practice flow with available context selected."""
    st.session_state["adaptive_practice_selection"] = {
        "student_id": student_id,
        "subject": subject,
        "topic": topic,
        "difficulty": "Beginner",
    }
    st.switch_page("pages/3_Practice.py")


@measure_function("ui.dashboard.statistics", provider="local", task="render")
def _render_statistics(stats: dict[str, object] | None) -> None:
    st.markdown("### Learning statistics")
    with st.container(key="dashboard-stat-grid"):
        columns = st.columns(4, gap="small")
        items = (
            ("Topics studied", str(stats["topics_studied"]) if stats else "—"),
            ("Quizzes attempted", str(stats["quizzes_completed"]) if stats else "—"),
            (
                "Average quiz score",
                f"{stats['average_score']:.1f}%" if stats and stats["average_score"] is not None else "—",
            ),
            (
                "Overall progress",
                f"{stats['overall_progress']:.0f}%" if stats and stats["overall_progress"] is not None else "—",
            ),
        )
        for column, (label, value) in zip(columns, items):
            with column:
                with st.container(border=True, key=f"dashboard-stat-{label.casefold().replace(' ', '-')}"):
                    st.metric(label, value)


@measure_function("ui.dashboard.actions", provider="local", task="render")
def _render_learning_actions(student_id: int) -> None:
    st.markdown("### Choose where to begin")
    with st.container(key="dashboard-action-grid"):
        columns = st.columns(2, gap="medium")
        actions = (
            ("Learning Path", "Review your current level and recommended next step.", "Open Learning Path", "path"),
            ("Practice", "Build confidence with a focused set of questions.", "Start Practice", "practice"),
        )
        for column, (title, description, label, action) in zip(columns, actions):
            with column:
                with st.container(border=True, key=f"dashboard-action-{action}"):
                    st.markdown(f"#### {title}")
                    st.markdown(f'<p class="dashboard-tile-description">{description}</p>', unsafe_allow_html=True)
                    if action == "path":
                        if st.button(label, type="primary", key="dashboard-open-path"):
                            st.switch_page("pages/5_Learning_Path.py")
                    elif st.button(label, key="dashboard-start-practice"):
                        _start_practice(student_id, "DSA")


@measure_function("ui.dashboard.subjects", provider="local", task="render")
def _render_subjects(
    student_id: int,
    progress_rows: list[dict[str, object]] | None,
    subject_stats: list[dict[str, object]] | None,
    *,
    has_error: bool = False,
) -> None:
    st.markdown("### Your subjects")
    progress_rows = progress_rows or []
    by_subject = {row["subject"].casefold(): row for row in (subject_stats or [])}
    with st.container(key="dashboard-subject-grid"):
        columns = st.columns(3, gap="small")
        for index, (column, (code, title, description)) in enumerate(zip(columns, SUBJECT_CARDS)):
            with column:
                with st.container(border=True, key=f"dashboard-subject-{index}"):
                    st.markdown(f"#### {code}")
                    st.caption(title)
                    st.markdown(f'<p class="dashboard-tile-description">{description}</p>', unsafe_allow_html=True)
                    record = by_subject.get(code.casefold())
                    average = record["average_score"] if record else None
                    st.metric("Average quiz performance", f"{average:.1f}%" if average is not None else "—")
                    if has_error:
                        st.caption("Quiz attempts: Data unavailable")
                        st.progress(0, text="Topic progress unavailable")
                    else:
                        st.caption(f"Quiz attempts: {record['attempts'] if record else 'No attempts yet'}")
                        rows = [row for row in progress_rows if row["subject"].casefold() == code.casefold()]
                        if rows:
                            progress = sum(float(row["progress_percent"]) for row in rows) / len(rows)
                            st.progress(int(progress), text=f"Topic progress · {progress:.0f}%")
                        else:
                            st.progress(0, text="No topic progress yet")
                    if st.button("View Subject", key=f"dashboard-view-subject-{index}"):
                        _start_practice(student_id, code)


@measure_function("ui.dashboard.recommendations", provider="local", task="render")
def _render_recommendations(student_id: int, progress_rows: list[sqlite3.Row] | None) -> None:
    st.markdown("### Recommended next topics")
    in_progress = [row for row in (progress_rows or []) if row["status"] == "in_progress"]
    if in_progress:
        st.caption("Based on topics already recorded in your account.")
        suggestions = [
            (row["subject"], row["topic"], f"Continue from {float(row['progress_percent']):.0f}% recorded progress.")
            for row in in_progress[:3]
        ]
    else:
        st.caption("General starting points to help you choose a subject.")
        suggestions = list(GENERAL_STARTING_POINTS)

    with st.container(key="dashboard-recommendation-grid"):
        columns = st.columns(3, gap="small")
        for index, (column, (subject, topic, detail)) in enumerate(zip(columns, suggestions)):
            with column:
                with st.container(border=True, key=f"dashboard-recommendation-{index}"):
                    st.caption(subject)
                    st.markdown(f"#### {topic}")
                    st.markdown(f'<p class="dashboard-tile-description">{detail}</p>', unsafe_allow_html=True)
                    if st.button("Start Learning", key=f"dashboard-start-topic-{index}"):
                        _start_practice(student_id, subject, topic)


@measure_function("dashboard.render")
def render_dashboard(student: dict[str, int | str]) -> None:
    """Render the student's actual learning metrics and next steps."""
    student_id = int(student["id"])
    first_name = str(student["display_name"]).split()[0]
    render_kicker("Your learning overview")
    st.title(f"Welcome back, {first_name}")
    st.markdown('<p class="al-page-description dashboard-welcome-copy">A simple view of your progress and a clear next step for your studies.</p>', unsafe_allow_html=True)

    try:
        with measure_stage("dashboard.data_preparation", provider="local", task="render"):
            overview = get_cached_dashboard_overview(student_id)
            stats = overview["stats"]
            progress_rows = overview["progress"]
            subject_stats = overview["subject_quiz_stats"]
        data_error = False
    except sqlite3.Error as error:
        st.error(f"Could not load your learning data: {error}")
        stats = progress_rows = subject_stats = None
        data_error = True

    _render_statistics(stats)
    if data_error and st.button("Retry loading", key="dashboard-retry"):
        st.rerun()

    _render_learning_actions(student_id)
    _render_subjects(student_id, progress_rows, subject_stats, has_error=data_error)
    _render_recommendations(student_id, progress_rows)
