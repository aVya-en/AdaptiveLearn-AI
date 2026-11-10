"""Deterministic learning performance calculations over database aggregates."""

from database.learning_data import get_learning_data_snapshot
from utils.performance import measure_function

MIN_CONCEPT_QUESTIONS = 5
STRONG_ACCURACY_PERCENT = 80.0
WEAK_ACCURACY_PERCENT = 50.0
TREND_CHANGE_THRESHOLD_PERCENT = 5.0
RECENT_WINDOW_SIZE = 5


def _percentage(numerator: int | float, denominator: int | float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator * 100 / denominator, 2)


def _subject_trend(attempts: list[dict[str, object]]) -> dict[str, object]:
    recent_scores = [float(row["score"]) for row in attempts if int(row["recent_rank"]) <= RECENT_WINDOW_SIZE]
    prior_scores = [float(row["score"]) for row in attempts if int(row["recent_rank"]) > RECENT_WINDOW_SIZE]
    recent_average = round(sum(recent_scores) / len(recent_scores), 2) if recent_scores else None
    prior_average = round(sum(prior_scores) / len(prior_scores), 2) if prior_scores else None
    if recent_average is None or prior_average is None:
        direction = "insufficient_history"
        change = None
    else:
        change = round(recent_average - prior_average, 2)
        if change >= TREND_CHANGE_THRESHOLD_PERCENT:
            direction = "improving"
        elif change <= -TREND_CHANGE_THRESHOLD_PERCENT:
            direction = "declining"
        else:
            direction = "stable"
    return {
        "direction": direction,
        "recent_average_score": recent_average,
        "previous_average_score": prior_average,
        "change_percentage_points": change,
        "recent_attempts": len(recent_scores),
        "previous_attempts": len(prior_scores),
    }


@measure_function("profile.build_transform", provider="local", task="learning_profile")
def build_learning_profile(snapshot: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    """Calculate subject and concept summaries from compact SQL aggregates."""
    attempts_by_subject: dict[str, list[dict[str, object]]] = {}
    for attempt in snapshot.get("recent_attempts", []):
        attempts_by_subject.setdefault(str(attempt["subject"]), []).append(attempt)

    concepts_by_subject: dict[str, list[dict[str, object]]] = {}
    for row in snapshot.get("concepts", []):
        attempted = int(row["attempted"])
        correct = int(row["correct"])
        accuracy = _percentage(correct, attempted)
        if attempted < MIN_CONCEPT_QUESTIONS:
            assessment = "insufficiently_assessed"
        elif accuracy is not None and accuracy >= STRONG_ACCURACY_PERCENT:
            assessment = "strong"
        elif accuracy is not None and accuracy <= WEAK_ACCURACY_PERCENT:
            assessment = "weak"
        else:
            assessment = "developing"
        concepts_by_subject.setdefault(str(row["subject"]), []).append({
            "topic": str(row["topic"]),
            "concept": str(row["concept"]),
            "questions_attempted": attempted,
            "correct_answers": correct,
            "incorrect_answers": attempted - correct,
            "accuracy": accuracy,
            "recent_questions_attempted": int(row["recent_attempted"]),
            "recent_accuracy": _percentage(int(row["recent_correct"]), int(row["recent_attempted"])),
            "assessment": assessment,
        })

    topics_by_subject: dict[str, list[dict[str, object]]] = {}
    for row in snapshot.get("topics", []):
        attempted = int(row["attempted"])
        correct = int(row["correct"])
        accuracy = _percentage(correct, attempted)
        if attempted < MIN_CONCEPT_QUESTIONS:
            assessment = "insufficiently_assessed"
        elif accuracy is not None and accuracy >= STRONG_ACCURACY_PERCENT:
            assessment = "strong"
        elif accuracy is not None and accuracy <= WEAK_ACCURACY_PERCENT:
            assessment = "weak"
        else:
            assessment = "developing"
        topics_by_subject.setdefault(str(row["subject"]), []).append({
            "topic": str(row["topic"]),
            "questions_attempted": attempted,
            "correct_answers": correct,
            "incorrect_answers": attempted - correct,
            "accuracy": accuracy,
            "recent_questions_attempted": int(row["recent_attempted"]),
            "recent_accuracy": _percentage(int(row["recent_correct"]), int(row["recent_attempted"])),
            "assessment": assessment,
        })

    metadata_by_subject = {
        str(row["subject"]): row for row in snapshot.get("response_metadata", [])
    }

    subject_summaries = []
    all_subject_attempt_rows = snapshot.get("subjects", [])
    total_questions = total_correct = 0
    for row in all_subject_attempt_rows:
        subject = str(row["subject"])
        subject_questions = int(row["total_questions"])
        subject_correct = int(row["correct_answers"])
        total_questions += subject_questions
        total_correct += subject_correct
        concepts = concepts_by_subject.get(subject, [])
        topics = topics_by_subject.get(subject, [])
        metadata = metadata_by_subject.get(subject)
        response_count = int(metadata["response_count"]) if metadata else 0
        missing_concept_count = int(metadata["missing_concept_count"]) if metadata else 0
        if response_count == 0 or missing_concept_count >= response_count:
            concept_metadata_status = "unavailable"
        elif missing_concept_count:
            concept_metadata_status = "partial"
        else:
            concept_metadata_status = "available"
        subject_summaries.append({
            "subject": subject,
            "quiz_count": int(row["quiz_count"]),
            "total_questions_attempted": subject_questions,
            "correct_answers": subject_correct,
            "incorrect_or_unanswered": max(0, subject_questions - subject_correct),
            "overall_accuracy": _percentage(subject_correct, subject_questions),
            "concepts_assessed": len(concepts),
            "concept_metadata_status": concept_metadata_status,
            "responses_without_concept_metadata": missing_concept_count,
            "strong_concepts": [item["concept"] for item in concepts if item["assessment"] == "strong"],
            "weak_concepts": [item["concept"] for item in concepts if item["assessment"] == "weak"],
            "developing_concepts": [item["concept"] for item in concepts if item["assessment"] == "developing"],
            "insufficiently_assessed_concepts": [
                item["concept"] for item in concepts if item["assessment"] == "insufficiently_assessed"
            ],
            "concept_performance": concepts,
            "topic_performance": topics,
            "recent_performance_trend": _subject_trend(attempts_by_subject.get(subject, [])),
        })

    return {
        "total_questions_attempted": total_questions,
        "overall_accuracy": _percentage(total_correct, total_questions),
        "concepts_assessed": sum(len(items) for items in concepts_by_subject.values()),
        "subjects": subject_summaries,
    }


def get_student_learning_profile(student_id: int) -> dict[str, object]:
    """Return a compact, student-scoped profile for future adaptive features."""
    if type(student_id) is not int or student_id < 1:
        raise ValueError("A valid student ID is required.")
    return build_learning_profile(get_learning_data_snapshot(student_id))
