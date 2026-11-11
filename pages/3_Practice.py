"""Authenticated quiz setup, one-question assessment, and review page."""

from time import perf_counter as _perf_counter

_page_started = _perf_counter()

import sqlite3
import uuid

import streamlit as st

from modules.adaptive_learning import recommended_difficulty
from modules.quiz_engine import (
    DIFFICULTIES,
    QUESTION_COUNTS,
    SUBJECT_TOPICS,
    QuizGenerationError,
    generate_quiz,
    submit_quiz,
)
from utils.auth_ui import require_student
from utils.performance import finish_page_timer, measure_stage
from ui.components import render_kicker

_page_timer = ("practice", _page_started)
st.set_page_config(page_title="Practice | AdaptiveLearn AI", page_icon="\u270D", layout="wide")
student = require_student()

render_kicker("Focused practice")
st.title("Practice")
st.markdown('<p class="al-page-description">Choose a subject and topic, then work through a focused set of questions.</p>', unsafe_allow_html=True)

student_id = int(student["id"])
quiz_state_key = f"practice_quiz_{student_id}"
if st.session_state.get("practice_owner_student_id") != student_id:
    for key in ("practice_subject", "practice_topic", "practice_difficulty"):
        st.session_state.pop(key, None)
    st.session_state.pop("practice_settings_open", None)
    st.session_state["practice_owner_student_id"] = student_id
quiz_state = st.session_state.get(quiz_state_key)


def _start_another_quiz() -> None:
    st.session_state.pop(quiz_state_key, None)
    st.session_state.pop("practice_settings_open", None)
    st.rerun()


def _render_results(state: dict) -> None:
    result = state["evaluation"]
    st.subheader("Quiz results")
    st.metric("Final score", f"{result['score_percentage']:.1f}%")
    totals = st.columns(4)
    totals[0].metric("Total questions", result["total_questions"])
    totals[1].metric("Correct", result["correct_answers"])
    totals[2].metric("Incorrect", result["incorrect_answers"])
    totals[3].metric("Unanswered", result["unanswered_questions"])
    st.caption(f"{state['subject']} · {state['topic']} · {state['difficulty']}")

    st.subheader("Question review")
    for number, review in enumerate(result["review"], start=1):
        if review["selected_answer"] is None:
            outcome = "Unanswered"
        else:
            outcome = "Correct" if review["is_correct"] else "Incorrect"
        with st.container(border=True):
            st.markdown(f"#### Question {number} · {outcome}")
            st.markdown(review["question"])
            st.write(f"**Your answer:** {review['selected_answer'] or 'Not answered'}")
            st.write(f"**Correct answer:** {review['correct_answer']}")
            if review["selected_answer"] is None:
                st.info("This question was left unanswered.")
            elif review["is_correct"]:
                st.success("Correct")
            else:
                st.error("Incorrect")
            with st.expander("Explanation"):
                st.markdown(review["explanation"])

    st.button("Start another quiz", type="primary", on_click=_start_another_quiz)


def _persist_submission(state: dict) -> None:
    try:
        submit_quiz(student_id, state)
    except (sqlite3.Error, ValueError, PermissionError, RuntimeError) as error:
        st.error(f"Could not save this quiz attempt: {error}")
    else:
        st.rerun()


def _apply_adaptive_difficulty() -> None:
    selected_subject = st.session_state.get("practice_subject")
    selected_topic = st.session_state.get("practice_topic")
    if selected_subject in SUBJECT_TOPICS:
        if selected_topic not in SUBJECT_TOPICS[selected_subject]:
            selected_topic = SUBJECT_TOPICS[selected_subject][0]
            st.session_state["practice_topic"] = selected_topic
        with measure_stage("practice.adaptive_difficulty_preparation", provider="local", task="render"):
            st.session_state["practice_difficulty"] = recommended_difficulty(
                student_id, selected_subject, selected_topic
            )


def _toggle_practice_settings() -> None:
    st.session_state["practice_settings_open"] = not bool(
        st.session_state.get("practice_settings_open", False)
    )


if quiz_state is None:
    adaptive_selection = st.session_state.pop("adaptive_practice_selection", None)
    if (
        isinstance(adaptive_selection, dict)
        and type(adaptive_selection.get("student_id")) is int
        and adaptive_selection["student_id"] == student_id
    ):
        if adaptive_selection.get("subject") in SUBJECT_TOPICS:
            st.session_state["practice_subject"] = adaptive_selection["subject"]
            if adaptive_selection.get("topic") in SUBJECT_TOPICS[adaptive_selection["subject"]]:
                st.session_state["practice_topic"] = adaptive_selection["topic"]
            if adaptive_selection.get("difficulty") in DIFFICULTIES:
                st.session_state["practice_difficulty"] = adaptive_selection["difficulty"]
    if st.session_state.get("practice_subject") not in SUBJECT_TOPICS:
        st.session_state["practice_subject"] = list(SUBJECT_TOPICS)[0]
    default_subject = st.session_state["practice_subject"]
    if st.session_state.get("practice_topic") not in SUBJECT_TOPICS[default_subject]:
        st.session_state["practice_topic"] = SUBJECT_TOPICS[default_subject][0]
    if st.session_state.get("practice_difficulty") not in DIFFICULTIES:
        with measure_stage("practice.adaptive_difficulty_preparation", provider="local", task="render"):
            st.session_state["practice_difficulty"] = recommended_difficulty(
                student_id, default_subject, st.session_state["practice_topic"]
            )
else:
    if quiz_state.get("student_id") != student_id:
        # Never allow another account to view a quiz left in this browser session.
        st.session_state.pop(quiz_state_key, None)
        st.rerun()

if quiz_state is not None:
    for key, value in (
        ("practice_subject", quiz_state["subject"]),
        ("practice_topic", quiz_state["topic"]),
        ("practice_difficulty", quiz_state["difficulty"]),
        ("practice_question_count", len(quiz_state["questions"])),
    ):
        if key not in st.session_state:
            st.session_state[key] = value


def _render_settings(*, quiz_exists: bool) -> tuple[str, str, str, int, bool, bool]:
    """Render existing quiz controls and report explicit generation actions."""
    st.subheader("Practice Settings")
    subject = st.selectbox(
        "Subject", list(SUBJECT_TOPICS), key="practice_subject",
        on_change=_apply_adaptive_difficulty,
    )
    topic_options = SUBJECT_TOPICS[subject]
    if st.session_state.get("practice_topic") not in topic_options:
        st.session_state["practice_topic"] = topic_options[0]
    topic = st.selectbox(
        "Topic", topic_options, key="practice_topic",
        on_change=_apply_adaptive_difficulty,
    )
    difficulty = st.selectbox("Difficulty", DIFFICULTIES, key="practice_difficulty")
    question_count = st.selectbox(
        "Number of questions", QUESTION_COUNTS, key="practice_question_count"
    )
    if quiz_exists:
        return subject, topic, difficulty, question_count, False, st.button(
            "Generate New Quiz"
        )
    return (
        subject, topic, difficulty, question_count,
        st.button("Generate Quiz", type="primary"),
        st.button("Generate New Quiz"),
    )


def _render_workspace(*, generate_requested: bool, force_new: bool) -> None:
    """Keep empty, loading, quiz, and result content in one workspace card."""
    with st.container(border=True, key="practice-workspace"):
        if generate_requested:
            request_key = f"practice_generation_pending_{student_id}"
            if st.session_state.get(request_key):
                st.info("Quiz generation is already in progress.")
            else:
                st.session_state[request_key] = True
                try:
                    with st.spinner("Generating and validating your quiz..."):
                        st.caption("Preparing questions and checking their answers.")
                        questions = generate_quiz(
                            subject, topic, difficulty, question_count, force_new=force_new
                        )
                except QuizGenerationError as error:
                    st.error(str(error))
                else:
                    st.session_state[quiz_state_key] = {
                        "student_id": student_id,
                        "subject": subject,
                        "topic": topic,
                        "difficulty": difficulty,
                        "questions": questions,
                        "answers": [None] * len(questions),
                        "current_index": 0,
                        "submitted": False,
                        "pending_submit": False,
                        "attempt_key": uuid.uuid4().hex,
                    }
                    st.session_state.pop("practice_settings_open", None)
                    st.rerun()
                finally:
                    st.session_state.pop(request_key, None)
        if quiz_state is None:
            render_kicker("Focused practice")
            st.markdown("### Ready to test your understanding?")
            st.markdown(
                '<p class="al-practice-empty-description">Choose your subject, topic, difficulty, '
                'and question count in Practice Settings, then generate a quiz to begin.</p>',
                unsafe_allow_html=True,
            )
            return
        if quiz_state.get("submitted"):
            _render_results(quiz_state)
            return

        questions = quiz_state["questions"]
        index = quiz_state["current_index"]
        question = questions[index]
        st.caption(f"{quiz_state['subject']} · {quiz_state['topic']} · {quiz_state['difficulty']}")
        st.progress((index + 1) / len(questions), text=f"Question {index + 1} of {len(questions)}")
        st.markdown(f"### {question['question']}")
        radio_key = f"practice_{quiz_state['attempt_key']}_answer_{index}"
        saved_index = quiz_state["answers"][index]
        selected = st.radio(
            "Choose one answer",
            question["options"],
            index=saved_index,
            key=radio_key,
            label_visibility="collapsed",
        )
        quiz_state["answers"][index] = question["options"].index(selected) if selected is not None else None

        with st.container(
            horizontal=True, horizontal_alignment="right", vertical_alignment="center",
            gap="small", key="practice-question-navigation",
        ):
            if st.button("Previous", disabled=index == 0):
                quiz_state["current_index"] -= 1
                st.rerun()
            if st.button("Next", disabled=index == len(questions) - 1):
                quiz_state["current_index"] += 1
                st.rerun()
        with st.container(
            horizontal=True, horizontal_alignment="right", vertical_alignment="center",
            key="practice-submit-action",
        ):
            if st.button("Submit Quiz", type="primary"):
                _persist_submission(quiz_state)


if quiz_state is None:
    with st.container(key="practice-empty-layout"):
        workspace_column, settings_column = st.columns(
            [3, 1], gap="large", vertical_alignment="top"
        )
        with settings_column:
            with st.container(border=True, key="practice-settings"):
                subject, topic, difficulty, question_count, generate_clicked, fresh_clicked = _render_settings(
                    quiz_exists=False
                )
        with workspace_column:
            _render_workspace(generate_requested=generate_clicked or fresh_clicked, force_new=fresh_clicked)
else:
    settings_open = bool(st.session_state.get("practice_settings_open", False))
    generate_clicked = fresh_clicked = False
    with st.container(key="practice-settings-toggle"):
        st.button(
            " ",
            icon=":material/settings:",
            help="Change settings",
            key="practice-settings-toggle-button", on_click=_toggle_practice_settings,
        )

    if settings_open:
        with st.container(key="practice-active-layout"):
            workspace_column, settings_column = st.columns(
                [3, 1], gap="large", vertical_alignment="top"
            )
            with settings_column:
                with st.container(border=True, key="practice-settings"):
                    subject, topic, difficulty, question_count, generate_clicked, fresh_clicked = _render_settings(
                        quiz_exists=True
                    )
            with workspace_column:
                _render_workspace(generate_requested=generate_clicked or fresh_clicked, force_new=fresh_clicked)
    else:
        subject = st.session_state["practice_subject"]
        topic = st.session_state["practice_topic"]
        difficulty = st.session_state["practice_difficulty"]
        question_count = st.session_state["practice_question_count"]
        _render_workspace(generate_requested=generate_clicked or fresh_clicked, force_new=fresh_clicked)
finish_page_timer(_page_timer)
