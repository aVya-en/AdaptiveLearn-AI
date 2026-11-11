"""Shared authentication checks and sidebar controls for Streamlit pages."""

import streamlit as st
from utils.performance import measure_function


@measure_function("sidebar.render_workspace")
def _render_workspace_sidebar(student: dict[str, int | str]) -> None:
    """Render account controls after the app's branding and navigation."""
    with st.sidebar:
        with st.container(key="adaptivelearn-sidebar-bottom"):
            st.markdown('<div class="adaptivelearn-section-label">ACCOUNT</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="adaptivelearn-account"><span class="adaptivelearn-status-dot"></span>'
                f'<div><strong>{_escape_html(str(student["display_name"]))}</strong>'
                '<small>Signed in</small></div></div>',
                unsafe_allow_html=True,
            )
            if st.button("Log out", key="adaptivelearn_logout", use_container_width=True):
                st.session_state.pop("student", None)
                st.switch_page("pages/0_Sign_In.py")


def _escape_html(value: str) -> str:
    """Escape account text before inserting it into sidebar HTML."""
    import html

    return html.escape(value)


@measure_function("authentication.require_student")
def require_student(*, show_usage_details: bool = True) -> dict[str, int | str]:
    """Show sign-in prompt when logged out; retain usage flag for caller compatibility."""
    student = st.session_state.get("student")
    if not _is_valid_student_profile(student):
        # Session state can outlive a failed login, logout, or interrupted rerun.
        # Discard malformed profiles before any page uses their identity.
        st.session_state.pop("student", None)
        st.warning("Sign in from the home page to view your learning workspace.")
        st.stop()
    _render_workspace_sidebar(student)
    return student


def _is_valid_student_profile(student: object) -> bool:
    """Check the minimum profile shape returned by the authentication service."""
    return (
        isinstance(student, dict)
        and type(student.get("id")) is int
        and student["id"] > 0
        and isinstance(student.get("display_name"), str)
        and bool(student["display_name"].strip())
        and isinstance(student.get("email"), str)
        and bool(student["email"].strip())
    )
