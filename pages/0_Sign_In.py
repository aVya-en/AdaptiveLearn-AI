"""AdaptiveLearn AI sign-in and account creation screens."""

from time import perf_counter as _perf_counter

_page_started = _perf_counter()

import streamlit as st

from database.db import DATABASE_ERRORS
from modules.auth import authenticate_student, register_student
from utils.config import load_configuration
from utils.performance import finish_page_timer

_page_timer = ("sign_in", _page_started)
load_configuration()
st.set_page_config(page_title="AdaptiveLearn AI | Sign in", page_icon="📘", layout="wide")

if "student" not in st.session_state:
    st.session_state.student = None

student = st.session_state.student
if student:
    st.switch_page("pages/1_Dashboard.py")
else:
    if "auth_screen" not in st.session_state:
        requested_screen = st.query_params.get("auth_screen", "signin")
        st.session_state.auth_screen = requested_screen if requested_screen in {"signin", "signup"} else "signin"

    def switch_auth_screen(screen: str) -> None:
        st.session_state.auth_screen = screen
        st.query_params["auth_screen"] = screen
        st.rerun()

    with st.container(key="auth-page-shell"):
        with st.container(key="auth-form"):
            st.markdown('<div class="auth-brand">AdaptiveLearn AI</div>', unsafe_allow_html=True)

            if st.session_state.auth_screen == "signup":
                st.markdown("## Create Account")
                st.markdown('<p class="auth-description">Create your account to begin learning.</p>', unsafe_allow_html=True)
                with st.form("register_form"):
                    full_name = st.text_input("Full Name", placeholder="Your name", autocomplete="name")
                    new_email = st.text_input("Email Address", type="email", icon="", placeholder="you@example.com")
                    new_password = st.text_input(
                        "Password", type="password", icon="", autocomplete="new-password"
                    )
                    confirm_password = st.text_input(
                        "Confirm Password", type="password", icon="", autocomplete="new-password"
                    )
                    with st.container(key="auth-primary-action"):
                        submitted = st.form_submit_button(
                            "Create Account", type="primary", use_container_width=True
                        )
                if submitted:
                    try:
                        created, message = register_student(full_name, new_email, new_password, confirm_password)
                    except DATABASE_ERRORS as error:
                        st.error(f"Could not create your account because of a database error: {error}")
                    else:
                        (st.success if created else st.error)(message)

                with st.container(key="auth-switch"):
                    st.markdown('<p class="auth-switch-message">Already have an account?</p>', unsafe_allow_html=True)
                    if st.button("Sign in", key="auth-nav-signin", type="tertiary"):
                        switch_auth_screen("signin")
            else:
                st.markdown("## Sign In")
                st.markdown('<p class="auth-description">Welcome back. Sign in to continue learning.</p>', unsafe_allow_html=True)
                with st.form("login_form"):
                    email = st.text_input("Email Address", type="email", icon="", placeholder="you@example.com")
                    password = st.text_input("Password", type="password", icon="", autocomplete="current-password")
                    with st.container(key="auth-primary-action"):
                        submitted = st.form_submit_button(
                            "Sign In", type="primary", use_container_width=True
                        )
                if submitted:
                    try:
                        profile = authenticate_student(email, password)
                    except DATABASE_ERRORS as error:
                        st.error(f"Could not sign in because of a database error: {error}")
                    else:
                        if profile:
                            st.session_state.student = profile
                            st.switch_page("pages/1_Dashboard.py")
                        else:
                            st.error("Email or password is incorrect.")

                with st.container(key="auth-switch"):
                    st.markdown('<p class="auth-switch-message">New to AdaptiveLearn AI?</p>', unsafe_allow_html=True)
                    if st.button("Create an account", key="auth-nav-signup", type="tertiary"):
                        switch_auth_screen("signup")

finish_page_timer(_page_timer)
