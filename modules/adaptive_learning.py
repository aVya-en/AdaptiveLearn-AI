"""Diagnostic assessment, adaptive difficulty, and personalized learning paths."""

from __future__ import annotations

import json
import re
from typing import Any

from database.learning_data import (
    get_current_adaptive_recommendation,
    get_latest_diagnostic_assessment,
    get_latest_topic_concept,
    get_latest_topic_practice_difficulty,
    get_learning_data_snapshot,
    save_adaptive_recommendation,
)
from database.db import initialize_database
from modules.adaptive_provider import generate_adaptive_content_with_metadata
from modules.learning_profile import get_student_learning_profile
from modules.quiz_engine import (
    DIFFICULTIES,
    QUIZ_RESPONSE_SCHEMA,
    SUBJECT_TOPICS,
    QuizGenerationError,
    evaluate_answers,
    submit_quiz,
    validate_quiz_payload,
)
from utils.performance import measure_function, measure_stage

SELF_ASSESSMENT_LEVELS = ("Beginner", "Intermediate", "Advanced", "Not sure")
DIAGNOSTIC_QUESTION_COUNT = 10
DIAGNOSTIC_MIN_ANSWERED = 8
DIAGNOSTIC_OUTPUT_TOKEN_LIMIT = 3500
RECOMMENDATION_OUTPUT_TOKEN_LIMIT = 700
RECOMMENDATION_TASK = "recommendation"

RECOMMENDATION_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "next_topic": {"type": "STRING"},
        "reason": {"type": "STRING"},
        "priority": {"type": "STRING", "enum": ["high", "medium", "low"]},
        "study_activity": {"type": "STRING"},
        "recommended_difficulty": {"type": "STRING", "enum": list(DIFFICULTIES)},
        "learning_objective": {"type": "STRING"},
    },
    "required": [
        "next_topic", "reason", "priority", "study_activity",
        "recommended_difficulty", "learning_objective",
    ],
}


class AdaptiveLearningError(RuntimeError):
    """Safe failure for diagnostic or adaptive learning operations."""


def _parse_structured_json(response_text: str) -> Any:
    """Parse provider JSON, allowing only a single complete Markdown code fence wrapper."""
    if not isinstance(response_text, str):
        raise QuizGenerationError("The diagnostic provider returned invalid JSON. Please try again.")
    candidate = response_text.strip().lstrip("\ufeff").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) < 3 or lines[0].strip().casefold() not in ("```", "```json") or lines[-1].strip() != "```":
            raise QuizGenerationError("The diagnostic provider returned invalid JSON. Please try again.")
        candidate = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        raise QuizGenerationError("The diagnostic provider returned invalid JSON. Please try again.") from None


@measure_function("adaptive.diagnostic.generate_total", provider="adaptive", task="diagnostic")
def generate_diagnostic_questions(
    student_id: int, subject: str, self_assessed_proficiency: str,
    *, with_metadata: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
    """Generate a metadata-grounded mixed-difficulty diagnostic using the shared adapter."""
    if type(student_id) is not int or student_id < 1:
        raise ValueError("A valid student ID is required.")
    if subject not in SUBJECT_TOPICS:
        raise ValueError("Choose a supported subject.")
    if self_assessed_proficiency not in SELF_ASSESSMENT_LEVELS:
        raise ValueError("Choose a valid self-assessed proficiency.")
    topics = SUBJECT_TOPICS[subject]
    with measure_stage("adaptive.diagnostic.prompt_construction", provider="local", task="diagnostic"):
        prompt = (
            f"Create exactly {DIAGNOSTIC_QUESTION_COUNT} original diagnostic multiple-choice questions for subject {subject}. "
            f"Available topic metadata: {json.dumps(topics, separators=(',', ':'))}. "
            f"Learner self-assessment: {self_assessed_proficiency}; do not use this as evidence of skill. "
            "Cover as many listed topics as possible. Assign a mix of Beginner, Intermediate, and Advanced difficulty, "
            "with at least two questions at each level. Use only the listed topics and return one distinct concise concept label per question. "
            "Each question needs four distinct options, one correct_option_index from 0 to 3, and a concise accurate explanation. "
            "Set subject, topic, and difficulty on each item. Return only JSON matching the supplied schema."
        )
    response_text, provider_metadata = generate_adaptive_content_with_metadata(
        prompt,
        QUIZ_RESPONSE_SCHEMA,
        task="diagnostic",
        student_scope=student_id,
        output_token_limit=DIAGNOSTIC_OUTPUT_TOKEN_LIMIT,
    )
    with measure_stage(
        "adaptive.diagnostic.response_parsing",
        provider=str(provider_metadata.get("provider", "unknown")), task="diagnostic",
    ):
        payload = _parse_structured_json(response_text)
    with measure_stage(
        "adaptive.diagnostic.validation",
        provider="local", task="diagnostic",
    ):
        validated = validate_quiz_payload(
            payload, subject, topics[0], "Intermediate", DIAGNOSTIC_QUESTION_COUNT,
            allow_mixed_metadata=True,
        )
    difficulty_counts = {level: sum(item["difficulty"] == level for item in validated) for level in DIFFICULTIES}
    if any(count < 2 for count in difficulty_counts.values()):
        raise QuizGenerationError("The diagnostic did not include enough questions at every difficulty level.")
    if len({item["topic"] for item in validated}) < min(5, len(topics)):
        raise QuizGenerationError("The diagnostic did not cover enough available subject topics.")
    return (validated, provider_metadata) if with_metadata else validated


def _diagnostic_result(
    self_assessed: str,
    evaluation: dict[str, Any],
    assessed_topics: set[str],
    available_topics: list[str],
    provider_metadata: dict[str, Any] | None = None,
) -> dict[str, object]:
    answered = evaluation["correct_answers"] + evaluation["incorrect_answers"]
    accuracy = round(evaluation["correct_answers"] * 100 / answered, 2) if answered else None
    required_topics = min(3, len(set(available_topics)))
    coverage_met = len(assessed_topics.intersection(available_topics)) >= required_topics
    if answered < DIAGNOSTIC_MIN_ANSWERED or not coverage_met:
        demonstrated = "Insufficient evidence"
        status = "insufficient_evidence"
    elif accuracy is not None and accuracy < 50:
        demonstrated = "Beginner"
        status = "assessed"
    elif accuracy is not None and accuracy < 80:
        demonstrated = "Intermediate"
        status = "assessed"
    else:
        demonstrated = "Advanced"
        status = "assessed"
    metadata = provider_metadata or {}
    return {
        "self_assessed_proficiency": self_assessed,
        "demonstrated_proficiency": demonstrated,
        "assessment_status": status,
        "answered_questions": answered,
        "assessed_topics": len(assessed_topics.intersection(available_topics)),
        "required_topics": required_topics,
        "topic_coverage_met": coverage_met,
        "assessment_note": None if coverage_met else "Topic coverage is inadequate for a subject-wide estimate.",
        "accuracy": accuracy,
        "provider": metadata.get("provider", "unknown"),
        "task": "diagnostic",
        "input_tokens": metadata.get("input_tokens"),
        "output_tokens": metadata.get("output_tokens"),
        "fallback_used": bool(metadata.get("fallback_used", False)),
    }


def submit_diagnostic(student_id: int, quiz_state: dict[str, Any]) -> dict[str, object]:
    """Score deterministically and save diagnostic responses with the regular quiz attempt."""
    if quiz_state.get("student_id") != student_id:
        raise PermissionError("This diagnostic does not belong to the signed-in student.")
    if quiz_state.get("submitted"):
        return dict(quiz_state.get("diagnostic_result") or {})
    answers = quiz_state.get("answers")
    questions = quiz_state.get("questions")
    if not isinstance(questions, list) or not isinstance(answers, list):
        raise ValueError("Diagnostic data is incomplete.")
    evaluation = evaluate_answers(questions, answers)
    available_topics = SUBJECT_TOPICS.get(quiz_state.get("subject"), [])
    assessed_topics = {
        question.get("topic")
        for question, answer in zip(questions, answers)
        if answer is not None
        and isinstance(question, dict)
        and isinstance(question.get("topic"), str)
        and question["topic"] in available_topics
    }
    result = _diagnostic_result(
        quiz_state["self_assessed_proficiency"], evaluation,
        assessed_topics, available_topics,
        quiz_state.get("provider_metadata"),
    )
    quiz_state["topic"] = "Initial diagnostic"
    quiz_state["difficulty"] = "Mixed"
    submit_quiz(student_id, quiz_state, diagnostic_data=result, evaluation=evaluation)
    quiz_state["diagnostic_result"] = result
    return result


def recommended_difficulty(
    student_id: int, subject: str, topic: str, *, concept: str | None = None,
) -> str:
    """Adjust from the latest concept in this topic; fall back to topic metrics if concepts are absent."""
    initialize_database()
    if type(student_id) is not int or student_id < 1 or subject not in SUBJECT_TOPICS:
        raise ValueError("A valid student and subject are required.")
    if topic not in SUBJECT_TOPICS[subject]:
        raise ValueError("Choose a supported subject topic.")
    with measure_stage(
        "adaptive.student_profile_retrieval", provider="local", task=RECOMMENDATION_TASK,
    ):
        profile = get_student_learning_profile(student_id)
    subject_profile = next((item for item in profile["subjects"] if item["subject"] == subject), None)
    topic_profile = next((item for item in subject_profile["topic_performance"] if item["topic"] == topic), None) if subject_profile else None
    latest_concept = concept or get_latest_topic_concept(student_id, subject, topic)
    concept_profile = next((
        item for item in (subject_profile["concept_performance"] if subject_profile else [])
        if item["topic"] == topic and item["concept"] == latest_concept
    ), None) if latest_concept else None
    if concept and concept_profile is None:
        raise ValueError("The selected concept has no answered performance data for this student and topic.")
    # Topic-level history remains the fallback only when no answered response has concept metadata.
    performance_profile = concept_profile if latest_concept else topic_profile

    current = get_latest_topic_practice_difficulty(student_id, subject, topic)
    if current is None:
        diagnostic = get_latest_diagnostic_assessment(student_id, subject)
        demonstrated = diagnostic.get("demonstrated_proficiency") if diagnostic else None
        current = "Intermediate" if demonstrated in ("Intermediate", "Advanced") else "Beginner"

    levels = list(DIFFICULTIES)
    index = levels.index(current)
    if performance_profile:
        recent_count = int(performance_profile["recent_questions_attempted"])
        recent_accuracy = performance_profile["recent_accuracy"]
        if recent_count >= 5 and recent_accuracy is not None and recent_accuracy >= 80:
            index = min(index + 1, len(levels) - 1)
        elif recent_count >= 3 and recent_accuracy is not None and recent_accuracy <= 50:
            index = max(index - 1, 0)
    return levels[index]


def _candidate_topics(subject: str, subject_profile: dict[str, Any]) -> list[dict[str, object]]:
    performance = {row["topic"]: row for row in subject_profile.get("topic_performance", [])}
    ranked = []
    for topic in SUBJECT_TOPICS[subject]:
        row = performance.get(topic)
        if row is None:
            rank = 2  # Known metadata, no assessment evidence yet.
            candidate = {"topic": topic, "assessment": "not_assessed", "questions_attempted": 0, "accuracy": None}
        else:
            candidate = {
                "topic": topic,
                "assessment": row["assessment"],
                "questions_attempted": row["questions_attempted"],
                "accuracy": row["accuracy"],
            }
            rank = {"weak": 0, "insufficiently_assessed": 1, "developing": 3, "strong": 4}.get(row["assessment"], 4)
        ranked.append((rank, candidate))
    ranked.sort(key=lambda pair: pair[0])
    return [candidate for _rank, candidate in ranked[:5]]


def _validate_recommendation(payload: Any, allowed_topics: set[str]) -> dict[str, str]:
    fields = set(RECOMMENDATION_SCHEMA["required"])
    if not isinstance(payload, dict) or set(payload) != fields:
        raise AdaptiveLearningError("The adaptive provider returned an invalid learning path.")
    if payload["next_topic"] not in allowed_topics:
        raise AdaptiveLearningError("The adaptive provider selected an unavailable topic.")
    if payload["priority"] not in ("high", "medium", "low"):
        raise AdaptiveLearningError("The adaptive provider returned an invalid priority.")
    if payload["recommended_difficulty"] not in DIFFICULTIES:
        raise AdaptiveLearningError("The adaptive provider returned an invalid difficulty.")
    safe_result = {}
    for field in ("reason", "study_activity", "learning_objective"):
        value = payload[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            raise AdaptiveLearningError("The adaptive provider returned incomplete learning guidance.")
        if re.search(
            r"\b(completed|finished|mastered|already learned|you(?:'ve| have)\s+(?:already\s+)?"
            r"(?:completed|finished|mastered|covered|learned|studied))\b",
            value,
            re.IGNORECASE,
        ):
            raise AdaptiveLearningError("The adaptive provider made an unsupported completion claim.")
        safe_result[field] = value.strip()
    return {
        "next_topic": payload["next_topic"],
        **safe_result,
        "priority": payload["priority"],
        "recommended_difficulty": payload["recommended_difficulty"],
    }


@measure_function("adaptive.recommendation.generate_total", provider="cache_or_adaptive", task="recommendation")
def get_learning_recommendation(
    student_id: int, subject: str, *, force_refresh: bool = False,
) -> dict[str, object]:
    """Return a per-student cached learning path or generate and persist a fresh one."""
    if type(student_id) is not int or student_id < 1 or subject not in SUBJECT_TOPICS:
        raise ValueError("A valid student and subject are required.")
    if not force_refresh:
        cached = get_current_adaptive_recommendation(student_id, subject)
        if cached:
            try:
                recommendation = json.loads(str(cached["payload_json"]))
            except (json.JSONDecodeError, TypeError):
                recommendation = None
            if isinstance(recommendation, dict):
                return {
                    "recommendation": recommendation,
                    "provider": cached["provider"], "task": cached["task"],
                    "input_tokens": cached["input_tokens"], "output_tokens": cached["output_tokens"],
                    "fallback_used": bool(cached["fallback_used"]), "cached": True,
                }

    profile = get_student_learning_profile(student_id)
    subject_profile = next((item for item in profile["subjects"] if item["subject"] == subject), None)
    if subject_profile is None:
        raise AdaptiveLearningError("Complete a diagnostic or practice quiz before requesting a personalized learning path.")
    candidates = _candidate_topics(subject, subject_profile)
    with measure_stage("adaptive.recommendation.prompt_construction", provider="local", task=RECOMMENDATION_TASK):
        compact_profile = {
            "total_questions_attempted": subject_profile["total_questions_attempted"],
            "overall_accuracy": subject_profile["overall_accuracy"],
            "recent_performance_trend": subject_profile["recent_performance_trend"],
            "strong_concepts": subject_profile["strong_concepts"][:8],
            "weak_concepts": subject_profile["weak_concepts"][:8],
            "developing_concepts": subject_profile["developing_concepts"][:8],
            "insufficiently_assessed_concepts": subject_profile["insufficiently_assessed_concepts"][:8],
            "concept_performance": subject_profile["concept_performance"][:12],
            "topic_performance": subject_profile["topic_performance"][:8],
        }
        prompt = (
            "Recommend one next learning step using only this student's measured performance and supplied topic metadata. "
            "Do not claim a topic was completed, mastered, or studied unless evidence explicitly supports it. "
            "Choose next_topic exactly from candidates. Explain the observed performance behind the recommendation. "
            "Give a concrete short study activity and one measurable learning objective. Difficulty is a suggestion; the application applies its own bounded rule. "
            f"Student subject profile: {json.dumps(compact_profile, separators=(',', ':'))}. "
            f"Available candidate topics: {json.dumps(candidates, separators=(',', ':'))}. "
            "Return only JSON matching the schema."
        )
    response_text, metadata = generate_adaptive_content_with_metadata(
        prompt,
        RECOMMENDATION_SCHEMA,
        RECOMMENDATION_TASK,
        student_scope=student_id,
        output_token_limit=RECOMMENDATION_OUTPUT_TOKEN_LIMIT,
    )
    try:
        with measure_stage(
            "adaptive.recommendation.response_parsing",
            provider=str(metadata.get("provider", "unknown")), task=RECOMMENDATION_TASK,
        ):
            raw = json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        raise AdaptiveLearningError("The adaptive provider returned invalid learning path data.") from None
    allowed = {str(candidate["topic"]) for candidate in candidates}
    with measure_stage(
        "adaptive.recommendation.validation",
        provider="local", task=RECOMMENDATION_TASK,
    ):
        recommendation = _validate_recommendation(raw, allowed)
    recommendation["recommended_difficulty"] = recommended_difficulty(
        student_id, subject, recommendation["next_topic"]
    )

    snapshot = get_learning_data_snapshot(student_id)
    subject_row = next((row for row in snapshot["subjects"] if row["subject"] == subject), None)
    source_attempt_id = int(subject_row["latest_attempt_id"]) if subject_row else None
    with measure_stage(
        "adaptive.recommendation.persistence",
        provider=str(metadata.get("provider", "unknown")), task=RECOMMENDATION_TASK,
    ):
        save_adaptive_recommendation(
            student_id,
            subject,
            json.dumps(recommendation, separators=(",", ":")),
            source_attempt_id,
            provider=str(metadata.get("provider", "unknown")),
            task=RECOMMENDATION_TASK,
            input_tokens=metadata.get("input_tokens"),
            output_tokens=metadata.get("output_tokens"),
            fallback_used=bool(metadata.get("fallback_used", False)),
        )
    return {
        "recommendation": recommendation,
        "provider": metadata.get("provider", "unknown"),
        "task": RECOMMENDATION_TASK,
        "input_tokens": metadata.get("input_tokens"),
        "output_tokens": metadata.get("output_tokens"),
        "fallback_used": bool(metadata.get("fallback_used", False)),
        "cached": False,
    }
