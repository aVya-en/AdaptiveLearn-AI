"""Reusable small presentation helpers used across student pages."""

from html import escape
import re

import streamlit as st
from utils.performance import measure_function


@measure_function("ui.component.kicker", provider="local", task="render")
def render_kicker(label: str) -> None:
    st.markdown(f'<div class="al-kicker">{escape(label)}</div>', unsafe_allow_html=True)


@measure_function("ui.component.page_intro", provider="local", task="render")
def render_page_intro(label: str, title: str, description: str) -> None:
    render_kicker(label)
    st.title(title)
    st.markdown(f'<p class="al-page-description">{escape(description)}</p>', unsafe_allow_html=True)


@measure_function("ui.component.empty_state", provider="local", task="render")
def render_empty_state(title: str, detail: str, action_label: str | None = None) -> None:
    st.markdown(
        '<div class="al-empty-state"><div class="al-empty-mark">+</div>'
        f'<strong>{escape(title)}</strong><span>{escape(detail)}</span></div>',
        unsafe_allow_html=True,
    )


@measure_function("ui.component.status", provider="local", task="render")
def render_status(label: str, tone: str = "neutral") -> None:
    safe_tone = tone if tone in {"neutral", "success", "warning", "error"} else "neutral"
    st.markdown(
        f'<span class="al-status al-status-{safe_tone}">{escape(label)}</span>',
        unsafe_allow_html=True,
    )


@measure_function("ui.component.concept_status", provider="local", task="render")
def render_concept_status(
    title: str,
    concepts: list[str],
    tone: str = "neutral",
    *,
    card_key: str,
) -> None:
    safe_tone = tone if tone in {"neutral", "success", "warning", "error", "info"} else "neutral"
    if concepts:
        tags = "".join(
            f'<div class="al-concept-tag">{escape(str(item))}</div>'
            for item in concepts
        )
    else:
        empty_messages = {
            "Strong": "No concepts classified as strong yet.",
            "Developing": "Not enough evidence to classify concepts yet.",
            "Weak": "No concepts currently classified as weak.",
            "Insufficiently assessed": "No concepts currently need further assessment.",
        }
        tags = f'<div class="al-concept-empty">{escape(empty_messages.get(title, "No concepts available yet."))}</div>'

    st.markdown(
        f'<section id="{escape(card_key, quote=True)}" class="al-concept-status al-concept-{safe_tone}" '
        f'aria-label="{escape(title)} concept mastery">'
        f'<strong class="al-concept-title">{escape(title)}</strong>'
        f'<span class="al-concept-count">{len(concepts)} {"concept" if len(concepts) == 1 else "concepts"}</span>'
        f'<div class="al-concept-tags" role="region" tabindex="0" aria-label="{escape(title)} concepts">{tags}</div>'
        '</section>',
        unsafe_allow_html=True,
    )


def _emphasize_values(text: str) -> str:
    """Escape recommendation text and emphasize numeric evidence without changing it."""
    escaped = escape(text)
    return re.sub(r"(?<![\w])([0-9]+(?:\.[0-9]+)?%?)(?![\w])", r"<strong>\1</strong>", escaped)


@measure_function("ui.component.learning_recommendation", provider="local", task="render")
def render_learning_recommendation(recommendation: dict[str, str], subject: str) -> None:
    """Render the complete recommendation in a stable, responsive hierarchy."""
    priority = escape(recommendation["priority"].title())
    difficulty = escape(recommendation["recommended_difficulty"])
    topic = escape(recommendation["next_topic"])
    st.markdown(
        '<section class="lp-recommendation-content" aria-label="Personalized learning recommendation">'
        '<div class="lp-recommendation-topline"><span class="lp-eyebrow">RECOMMENDED NEXT STEP</span>'
        f'<span class="lp-badge lp-priority-{priority.casefold()}">{priority} priority</span></div>'
        f'<h2 class="lp-topic-heading">{topic}</h2>'
        '<div class="lp-recommendation-labels">'
        f'<span class="lp-badge lp-subject-badge">{escape(subject)}</span>'
        f'<span class="lp-badge lp-difficulty-badge">{difficulty} difficulty</span></div>'
        '<div class="lp-recommendation-explanation"><span class="lp-section-label">Why this is recommended</span>'
        f'<p class="lp-recommendation-reason">{_emphasize_values(recommendation["reason"])}</p></div>'
        '<div class="lp-recommendation-details">'
        '<div class="lp-recommendation-detail"><span class="lp-section-label">Study activity</span>'
        f'<p>{_emphasize_values(recommendation["study_activity"])}</p></div>'
        '<div class="lp-recommendation-detail"><span class="lp-section-label">Learning objective</span>'
        f'<p>{_emphasize_values(recommendation["learning_objective"])}</p></div>'
        '</div></section>',
        unsafe_allow_html=True,
    )
