"""Student-scoped concept accuracy detail report."""

from time import perf_counter as _perf_counter

_page_started = _perf_counter()

import sqlite3

import streamlit as st

from modules.learning_profile import get_student_learning_profile
from ui.components import render_empty_state, render_kicker
from utils.auth_ui import require_student
from utils.performance import finish_page_timer
from utils.streamlit_ui import render_static_table
from utils.style import apply_app_style

_page_timer = ("progress_concepts", _page_started)
st.set_page_config(page_title="Concept Performance | AdaptiveLearn AI", page_icon="📈", layout="wide")
student = require_student()
apply_app_style()

if st.button("← Back to Progress", key="progress-concepts-back"):
    st.switch_page("pages/4_Progress.py")
render_kicker("Your learning evidence")
st.title("Concept Performance")
st.markdown(
    '<p class="al-page-description">Review answered questions, accuracy and evidence status for each tracked concept.</p>',
    unsafe_allow_html=True,
)

try:
    profile = get_student_learning_profile(int(student["id"]))
except sqlite3.Error as error:
    st.error(f"Could not load your concept performance: {error}")
else:
    subjects = profile["subjects"]
    if not subjects:
        render_empty_state(
            "No concept history yet",
            "Complete a quiz with answered responses to start tracking concept performance.",
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

        concepts = selected["concept_performance"]
        categories = (
            ("Strong", "strong"),
            ("Developing", "developing"),
            ("Weak", "weak"),
            ("Insufficiently assessed", "insufficiently_assessed"),
        )
        category_columns = st.columns(4, gap="small")
        for column, (label, assessment) in zip(category_columns, categories):
            count = sum(item["assessment"] == assessment for item in concepts)
            with column:
                st.metric(label, str(count))

        if concepts:
            render_static_table(
                ["Concept", "Topic", "Questions answered", "Accuracy", "Status"],
                [
                    (
                        item["concept"], item["topic"], item["questions_attempted"],
                        f"{item['accuracy']:.1f}%" if item["accuracy"] is not None else "Unavailable",
                        item["assessment"].replace("_", " ").title(),
                    )
                    for item in concepts
                ],
            )
        elif selected["concept_metadata_status"] == "unavailable":
            render_empty_state(
                "Concept labels unavailable",
                "Saved responses for this subject do not include concept labels, so there are no concept-level accuracy results to display.",
            )
        else:
            render_empty_state(
                "No tracked concepts yet",
                "Concept-level results will appear as answered responses include concept metadata.",
            )

finish_page_timer(_page_timer)
