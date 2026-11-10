"""Student-scoped diagnostics and personalized next-step learning path."""

from time import perf_counter as _perf_counter

_page_started = _perf_counter()

import sqlite3
import json
import uuid

import streamlit as st

from database.learning_data import (
    get_current_adaptive_recommendation,
    get_latest_diagnostic_assessment,
)
from modules.adaptive_learning import (
    AdaptiveLearningError,
    SELF_ASSESSMENT_LEVELS,
    generate_diagnostic_questions,
    get_learning_recommendation,
    submit_diagnostic,
)
from modules.learning_profile import get_student_learning_profile
from modules.quiz_engine import QuizGenerationError, SUBJECT_TOPICS
from modules.ai_tutor import TutorServiceError
from utils.auth_ui import require_student
from utils.performance import finish_page_timer
from utils.style import apply_app_style
from ui.components import render_concept_status, render_kicker, render_learning_recommendation, render_status

_page_timer = ("learning_path", _page_started)
st.set_page_config(page_title="Learning Path | AdaptiveLearn AI", page_icon="🧭", layout="wide")
student = require_student(show_usage_details=False)
apply_app_style()
student_id = int(student["id"])

subject_options = list(SUBJECT_TOPICS)
if st.session_state.get("learning_path_subject") not in subject_options:
    st.session_state["learning_path_subject"] = subject_options[0]
subject = st.session_state["learning_path_subject"]
diagnostic_key = f"learning_diagnostic_{student_id}_{subject}"
diagnostic_state = st.session_state.get(diagnostic_key)
latest_diagnostic = get_latest_diagnostic_assessment(student_id, subject)

try:
    profile = get_student_learning_profile(student_id)
    subject_profile = next((row for row in profile["subjects"] if row["subject"] == subject), None)
    profile_error = None
except sqlite3.Error as error:
    subject_profile = None
    profile_error = f"Could not load your performance profile: {error}"

recommendation_row = get_current_adaptive_recommendation(student_id, subject)
recommendation = None
if recommendation_row:
    try:
        recommendation = json.loads(str(recommendation_row["payload_json"]))
    except (ValueError, TypeError):
        recommendation = None

st.markdown("### Your learning overview")
if latest_diagnostic:
    overview_metrics = (
        ("lp-overview-self", "Self-assessed", latest_diagnostic["self_assessed_proficiency"]),
        ("lp-overview-demonstrated", "Demonstrated", latest_diagnostic["demonstrated_proficiency"]),
        ("lp-overview-answered", "Questions answered", f"{latest_diagnostic['answered_questions']} / 10"),
        (
            "lp-overview-accuracy",
            "Subject accuracy",
            f"{latest_diagnostic['accuracy']:.1f}%" if latest_diagnostic["accuracy"] is not None else "—",
        ),
    )
    with st.container(key="lp-overview-grid"):
        metric_columns = st.columns(4, gap="small")
        for column, (tile_key, label, value) in zip(metric_columns, overview_metrics):
            with column:
                with st.container(border=True, key=tile_key):
                    st.metric(label, value)
else:
    with st.container(border=True, key="lp-overview-empty"):
        st.markdown("#### Your baseline will appear here")
        st.caption("Complete a short diagnostic to establish a starting point for this subject.")

header_columns = st.columns([3.6, 1.2], gap="small", vertical_alignment="center")
with header_columns[0]:
    render_kicker("Personalized learning")
    st.title("Learning Path")
    st.markdown(
        '<p class="al-page-description">Review your progress and choose a focused next step.</p>',
        unsafe_allow_html=True,
    )
with header_columns[1]:
    with st.container(key="lp-subject-control"):
        subject = st.selectbox("Subject", subject_options, key="learning_path_subject", width="stretch")

with st.container(border=True, key="lp-diagnostic-card"):
    diagnostic_columns = st.columns([3, 1.2], gap="medium", vertical_alignment="center")
    with diagnostic_columns[0]:
        st.markdown("#### Diagnostic")
        if latest_diagnostic:
            if latest_diagnostic["assessment_status"] == "insufficient_evidence":
                render_status("Insufficient evidence", "warning")
                note = latest_diagnostic.get("assessment_note") or (
                    "More answers across the subject are needed for a reliable level estimate."
                )
                st.caption(note)
            else:
                render_status("Complete", "success")
        else:
            render_status("Not started", "neutral")
            st.caption("A short mixed-difficulty diagnostic sets your baseline.")
    with diagnostic_columns[1]:
        with st.container(key="lp-diagnostic-controls"):
            self_assessed = st.selectbox(
                "Self-assessed proficiency",
                SELF_ASSESSMENT_LEVELS,
                key=f"learning_self_assessed_{student_id}_{subject}",
                width="stretch",
            )
            with st.container(key="lp-diagnostic-action"):
                start_diagnostic = st.button(
                    "Start diagnostic" if not latest_diagnostic else "Retake diagnostic",
                    type="primary",
                    width="stretch",
                )

if start_diagnostic:
    try:
        with st.spinner("Preparing your diagnostic assessment..."):
            questions, provider_metadata = generate_diagnostic_questions(
                student_id, subject, self_assessed, with_metadata=True
            )
        state = {
            "student_id": student_id,
            "subject": subject,
            "topic": "Initial diagnostic",
            "difficulty": "Mixed",
            "self_assessed_proficiency": self_assessed,
            "provider_metadata": provider_metadata,
            "questions": questions,
            "answers": [None] * len(questions),
            "submitted": False,
            "attempt_key": uuid.uuid4().hex,
        }
        st.session_state[diagnostic_key] = state
        st.rerun()
    except (AdaptiveLearningError, TutorServiceError, QuizGenerationError, ValueError) as error:
        st.error(str(error))

if diagnostic_state and not diagnostic_state.get("submitted"):
    if diagnostic_state.get("student_id") != student_id or diagnostic_state.get("subject") != subject:
        st.session_state.pop(diagnostic_key, None)
        st.rerun()
    st.subheader("Answer the diagnostic questions")
    for index, question in enumerate(diagnostic_state["questions"]):
        st.markdown(f"**{index + 1}. {question['question']}**")
        st.caption(f"{question['topic']} · {question['difficulty']}")
        selected_index = st.radio(
            f"Answer for diagnostic question {index + 1}",
            range(len(question["options"])),
            format_func=lambda option_index, opts=question["options"]: opts[option_index],
            index=diagnostic_state["answers"][index],
            key=f"{diagnostic_state['attempt_key']}_answer_{index}",
            label_visibility="collapsed",
        )
        diagnostic_state["answers"][index] = selected_index
    if st.button("Submit diagnostic", type="primary"):
        try:
            submit_diagnostic(student_id, diagnostic_state)
            st.rerun()
        except (sqlite3.Error, ValueError, PermissionError, RuntimeError) as error:
            st.error(f"Could not save the diagnostic: {error}")

st.markdown("### Concept mastery")
if profile_error:
    st.error(profile_error)
if subject_profile:
    concept_groups = (
        ("Strong", subject_profile["strong_concepts"], "success"),
        ("Developing", subject_profile["developing_concepts"], "info"),
        ("Weak", subject_profile["weak_concepts"], "warning"),
        ("Insufficiently assessed", subject_profile["insufficiently_assessed_concepts"], "neutral"),
    )
    with st.container(key="lp-concept-grid"):
        concept_columns = st.columns(4, gap="small")
        for column, (label, concepts, tone) in zip(concept_columns, concept_groups):
            with column:
                card_key = f"lp-concept-card-{label.casefold().replace(' ', '-')}"
                render_concept_status(label, concepts, tone, card_key=card_key)
else:
    with st.container(border=True, key="lp-concept-empty"):
        st.markdown("#### Concept results will appear here")
        st.caption("Complete a practice quiz to build concept-level evidence.")

st.markdown("### Recommended next step")
start_practice = False
generate_path = False
with st.container(border=True, key="lp-recommendation-card"):
    if recommendation:
        render_learning_recommendation(recommendation, subject)
        with st.container(key="lp-recommendation-actions"):
            action_columns = st.columns(2, gap="small")
            with action_columns[0]:
                start_practice = st.button("Start practice", type="primary", width="content")
            with action_columns[1]:
                generate_label = "Refresh path"
                generate_path = st.button(
                    generate_label,
                    type="secondary",
                    disabled=subject_profile is None,
                    key="lp-generate-action",
                    width="content",
                )
    else:
        st.markdown("#### Build enough evidence for a recommendation")
        st.caption("Complete the diagnostic above or take a practice quiz to shape your next step.")
        with st.container(key="lp-recommendation-actions"):
            action_columns = st.columns(2, gap="small")
            with action_columns[1]:
                generate_path = st.button(
                    "Generate learning path",
                    type="primary",
                    disabled=subject_profile is None,
                    key="lp-generate-action",
                    width="content",
                )

if start_practice:
    st.session_state["adaptive_practice_selection"] = {
        "student_id": student_id,
        "subject": subject,
        "topic": recommendation["next_topic"],
        "difficulty": recommendation["recommended_difficulty"],
    }
    st.switch_page("pages/3_Practice.py")

if generate_path:
    try:
        with st.spinner("Analyzing your measured performance..."):
            get_learning_recommendation(student_id, subject, force_refresh=True)
        st.success("Your learning path is up to date.")
        st.rerun()
    except (AdaptiveLearningError, TutorServiceError, ValueError, sqlite3.Error) as error:
        st.error(str(error))

finish_page_timer(_page_timer)
