"""Authenticated Gemini tutoring chat interface."""

from time import perf_counter as _perf_counter

_page_started = _perf_counter()

import streamlit as st

from modules.ai_tutor import (
    TutorServiceError,
    generate_tutor_response,
    get_student_conversation,
    tutor_request_fingerprint,
)
from utils.auth_ui import require_student
from utils.config import get_gemini_api_key, load_configuration
from utils.performance import finish_page_timer
from ui.components import render_kicker

_page_timer = ("ai_tutor", _page_started)
st.set_page_config(page_title="AI Tutor | AdaptiveLearn AI", page_icon="\U0001F4D8", layout="wide")
load_configuration()
student = require_student()


SUBJECT_TOPICS = {
    "Data Structures and Algorithms": [
        "Arrays and strings", "Linked lists", "Stacks and queues", "Hash tables",
        "Trees and binary search trees", "Graphs", "Sorting and searching", "Big O analysis",
    ],
    "Python Programming": [
        "Variables and data types", "Control flow", "Functions", "Lists and dictionaries",
        "Object-oriented programming", "Exceptions", "Modules and packages", "File handling",
    ],
    "Database Management Systems": [
        "Relational model", "SQL queries", "Joins", "Keys and constraints",
        "Database normalization", "Transactions", "Indexes", "ER diagrams",
    ],
}
SUGGESTIONS = {
    "Data Structures and Algorithms": [
        "Explain the time complexity of binary search.",
        "When should I use a stack instead of a queue?",
        "Walk me through reversing a linked list.",
    ],
    "Python Programming": [
        "Explain the difference between a list and a tuple.",
        "Show me how Python functions use parameters and return values.",
        "Why should I handle exceptions in a program?",
    ],
    "Database Management Systems": [
        "Explain primary keys and foreign keys with an example.",
        "How does a SQL JOIN combine rows from two tables?",
        "Why do databases use normalization?",
    ],
}

if "tutor_settings_open" not in st.session_state:
    st.session_state["tutor_settings_open"] = True
st.session_state.setdefault("tutor_subject_selection", "Data Structures and Algorithms")
st.session_state.setdefault("tutor_topic_selection", SUBJECT_TOPICS["Data Structures and Algorithms"][0])
st.session_state.setdefault("tutor_difficulty_selection", "Beginner")

settings_open = st.session_state["tutor_settings_open"]
if settings_open:
    render_kicker("Your study companion")
    st.title("AI Tutor")
    st.markdown('<p class="al-page-description">Ask a question, explore an idea, and build understanding step by step.</p>', unsafe_allow_html=True)
else:
    with st.container(key="tutor-collapsed-header"):
        heading_column, open_column = st.columns([20, 1], gap="small")
        with heading_column:
            render_kicker("Your study companion")
            st.title("AI Tutor")
            st.markdown('<p class="al-page-description">Ask a question, explore an idea, and build understanding step by step.</p>', unsafe_allow_html=True)
        with open_column:
            if st.button("⚙", key="tutor_drawer_open", help="Open tutor settings", use_container_width=True):
                st.session_state["tutor_settings_open"] = True
                st.rerun()

with st.container(key="tutor-layout"):
    if settings_open:
        conversation_column, settings_column = st.columns(
            [3, 1], gap="medium", vertical_alignment="top"
        )
        with settings_column:
            with st.container(key="tutor-settings"):
                with st.container(key="tutor-drawer-header"):
                    title_column, close_column = st.columns([5, 1], gap="small")
                    with title_column:
                        st.markdown("#### Tutor settings")
                    with close_column:
                        if st.button("×", key="tutor_drawer_close", help="Close tutor settings", use_container_width=True):
                            st.session_state["tutor_settings_open"] = False
                            st.rerun()

                if "_tutor_subject_widget" not in st.session_state:
                    st.session_state["_tutor_subject_widget"] = st.session_state["tutor_subject_selection"]
                subject = st.selectbox("Subject", list(SUBJECT_TOPICS), key="_tutor_subject_widget")
                st.session_state["tutor_subject_selection"] = subject
                if (
                    "_tutor_topic_widget" not in st.session_state
                    or st.session_state["_tutor_topic_widget"] not in SUBJECT_TOPICS[subject]
                ):
                    saved_topic = st.session_state["tutor_topic_selection"]
                    st.session_state["_tutor_topic_widget"] = (
                        saved_topic if saved_topic in SUBJECT_TOPICS[subject] else SUBJECT_TOPICS[subject][0]
                    )
                topic = st.selectbox("Topic", SUBJECT_TOPICS[subject], key="_tutor_topic_widget")
                st.session_state["tutor_topic_selection"] = topic
                if "_tutor_difficulty_widget" not in st.session_state:
                    st.session_state["_tutor_difficulty_widget"] = st.session_state["tutor_difficulty_selection"]
                difficulty = st.selectbox(
                    "Difficulty", ["Beginner", "Intermediate", "Advanced"], key="_tutor_difficulty_widget"
                )
                st.session_state["tutor_difficulty_selection"] = difficulty
                if st.button("Clear conversation", key=f"tutor_clear_{student['id']}", use_container_width=True):
                    conversation = get_student_conversation(
                        st.session_state, student["id"], subject, topic, difficulty
                    )
                    conversation["messages"] = []
                    conversation.pop("pending_request", None)
                    conversation.pop("inflight_request_fingerprint", None)
                    conversation.pop("completed_request_fingerprint", None)
                    st.rerun()
                st.caption("Changing subject, topic, or difficulty starts a fresh conversation. Chats are kept separately for each signed-in account in this browser session.")
    else:
        conversation_column = st.container()
        subject = st.session_state["tutor_subject_selection"]
        if st.session_state["tutor_topic_selection"] not in SUBJECT_TOPICS[subject]:
            st.session_state["tutor_topic_selection"] = SUBJECT_TOPICS[subject][0]
        topic = st.session_state["tutor_topic_selection"]
        difficulty = st.session_state["tutor_difficulty_selection"]

    conversation = get_student_conversation(
        st.session_state, student["id"], subject, topic, difficulty
    )

    with conversation_column:
        with st.container(key="tutor-conversation"):
            transcript = st.container(height=520, key="tutor-transcript")
            with transcript:
                if not conversation["messages"]:
                    st.markdown(
                        '<div class="al-tutor-welcome"><div class="al-kicker">READY WHEN YOU ARE</div>'
                        '<h3>What would you like to understand?</h3>'
                        '<p>Choose a prompt below or ask your own question. Your tutor will guide you through the reasoning.</p></div>',
                        unsafe_allow_html=True,
                    )
                if not get_gemini_api_key():
                    st.warning("Tutor setup is incomplete. Configure GEMINI_API_KEY_1, GEMINI_API_KEY_2, or GEMINI_API_KEY_3 in your environment or Streamlit secrets to enable Gemini responses.")

                for message in conversation["messages"]:
                    with st.chat_message(message["role"]):
                        st.markdown(message["content"])

                st.markdown("**Try asking**")
                suggestion_cols = st.columns(3)
                selected_prompt = None
                pending = conversation.get("pending_request")
                for index, prompt in enumerate(SUGGESTIONS[subject]):
                    with suggestion_cols[index]:
                        if st.button(
                            prompt,
                            key=f"tutor_suggestion_{student['id']}_{subject}_{index}",
                            use_container_width=True,
                            disabled=bool(pending and pending.get("failed")),
                        ):
                            selected_prompt = prompt

                retry_requested = False
                if pending and pending.get("failed"):
                    st.warning("Your message is saved. Retry when ready, or clear the conversation to discard it.")
                    retry_requested = st.button("Retry last message", key=f"tutor_retry_{student['id']}")

            # In a nested layout Streamlit renders chat_input inline, so it stays
            # with the conversation rather than pinning across the whole page.
            typed_prompt = st.chat_input(
                f"Ask about {topic.lower()}...",
                disabled=bool(pending and pending.get("failed")),
            )
with conversation_column:
    question = pending["question"] if retry_requested and pending else (typed_prompt or selected_prompt)
    if question and not question.strip():
        with transcript:
            st.warning("Enter a question before sending.")
    elif question:
        is_retry = bool(retry_requested and pending)
        request_history = list(pending["history"]) if is_retry else list(conversation["messages"])
        fingerprint = pending["fingerprint"] if is_retry else tutor_request_fingerprint(
            question, request_history, subject, topic, difficulty
        )
        if not is_retry and fingerprint in {
            conversation.get("inflight_request_fingerprint"),
            conversation.get("completed_request_fingerprint"),
        }:
            with transcript:
                st.info("This message is already being handled or has just been answered.")
        else:
            if not is_retry:
                conversation["pending_request"] = {
                    "question": question,
                    "history": request_history,
                    "fingerprint": fingerprint,
                    "failed": False,
                }
                conversation["messages"].append({"role": "user", "content": question})
            conversation["inflight_request_fingerprint"] = fingerprint
            with transcript:
                if not is_retry:
                    with st.chat_message("user"):
                        st.markdown(question)
                with st.chat_message("assistant"):
                    with st.spinner("AdaptiveLearn AI is thinking..."):
                        try:
                            answer = generate_tutor_response(
                                question=question,
                                history=request_history,
                                subject=subject,
                                topic=topic,
                                difficulty=difficulty,
                                student_name=str(student["display_name"]).split()[0],
                            )
                        except TutorServiceError as error:
                            conversation["pending_request"]["failed"] = True
                            conversation.pop("inflight_request_fingerprint", None)
                            st.error(str(error))
                        else:
                            conversation["messages"].append({"role": "assistant", "content": answer})
                            conversation.pop("pending_request", None)
                            conversation["completed_request_fingerprint"] = fingerprint
                            conversation.pop("inflight_request_fingerprint", None)
                            st.rerun()
finish_page_timer(_page_timer)
