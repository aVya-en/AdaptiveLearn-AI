"""Shared authentication checks and sidebar controls for Streamlit pages."""

import streamlit as st
from modules.ai_tutor import get_api_usage_stats
from modules.adaptive_provider import get_adaptive_provider_usage
from utils.performance import measure_function


@measure_function("sidebar.render_workspace")
def _render_workspace_sidebar(student: dict[str, int | str], *, show_usage_details: bool = True) -> None:
    """Render branding, account controls, and compact local API usage metrics."""
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

            if show_usage_details:
                st.markdown('<div class="adaptivelearn-section-label">LOCAL API USAGE</div>', unsafe_allow_html=True)
                with st.expander("Usage details"):
                    usage = get_api_usage_stats()
                    adaptive_usage = get_adaptive_provider_usage()
                    lines = [
                        f"**Tutor / quiz requests:** {usage['tutor_api_requests']} / {usage['quiz_generation_api_requests']}",
                        f"**Successful / failed calls:** {usage['successful_api_calls']} / {usage['failed_api_calls']}",
                        f"**Primary / fallback requests:** {usage['primary_model_requests']} / {usage['fallback_model_requests']}",
                        f"**Quiz cache reuse:** {usage['cached_quiz_retrievals']}",
                        f"**Adaptive requests (Gemini):** {usage['adaptive_api_requests']}",
                        f"**Adaptive Groq requests / Gemini primary / fallbacks:** {adaptive_usage['groq_requests']} / {adaptive_usage['gemini_primary_requests']} / {adaptive_usage['gemini_fallbacks']}",
                    ]
                    hit_rate = usage["quiz_cache_hit_rate"]
                    lines.append(f"**Quiz cache hit rate:** {hit_rate:.0%}" if hit_rate is not None else "**Quiz cache hit rate:** unavailable")
                    prompt_tokens = usage["estimated_prompt_tokens"]
                    response_tokens = usage["estimated_response_tokens"]
                    lines.extend((
                        f"**Prompt / response tokens reported:** {prompt_tokens if prompt_tokens is not None else 'unavailable'} / {response_tokens if response_tokens is not None else 'unavailable'}",
                    ))
                    for feature, label in (("tutor", "Tutor"), ("quiz_generation", "Quiz"), ("adaptive", "Adaptive")):
                        feature_prompt = usage[f"{feature}_prompt_tokens_total"]
                        feature_response = usage[f"{feature}_response_tokens_total"]
                        prompt_avg = usage[f"average_{feature}_prompt_tokens"]
                        response_avg = usage[f"average_{feature}_response_tokens"]
                        lines.append(f"**{label} prompt / response tokens:** {feature_prompt} / {feature_response}")
                        if prompt_avg is not None or response_avg is not None:
                            prompt_text = f"{prompt_avg:.1f}" if prompt_avg is not None else "unavailable"
                            response_text = f"{response_avg:.1f}" if response_avg is not None else "unavailable"
                            lines.append(f"**{label} average tokens per reported call:** {prompt_text} / {response_text}")
                    st.markdown("\n\n".join(lines))
                    st.caption("Application process counters only; not Google's official quota measurements.")


def _escape_html(value: str) -> str:
    """Escape account text before inserting it into sidebar HTML."""
    import html

    return html.escape(value)


@measure_function("authentication.require_student")
def require_student(*, show_usage_details: bool = True) -> dict[str, int | str]:
    """Show the sign-in prompt and stop page execution when logged out."""
    student = st.session_state.get("student")
    if not _is_valid_student_profile(student):
        # Session state can outlive a failed login, logout, or interrupted rerun.
        # Discard malformed profiles before any page uses their identity.
        st.session_state.pop("student", None)
        st.warning("Sign in from the home page to view your learning workspace.")
        st.stop()
    _render_workspace_sidebar(student, show_usage_details=show_usage_details)
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
