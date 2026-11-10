"""AI-generated MCQ quiz creation, validation, and deterministic scoring."""

import json
import math
import re
import threading
import time
from concurrent.futures import Future
from copy import deepcopy
from typing import Any, Sequence

from database.db import save_quiz_attempt
from modules.ai_tutor import (
    TutorServiceError,
    generate_structured_content,
    get_gemini_model,
    record_cached_quiz_retrieval,
    record_quiz_cache_lookup,
)
from utils.performance import measure_function, measure_stage

SUBJECT_TOPICS = {
    "DSA": [
        "Arrays and strings",
        "Linked lists",
        "Stacks and queues",
        "Hash tables",
        "Trees and binary search trees",
        "Graphs",
        "Sorting and searching",
        "Big O analysis",
    ],
    "Python": [
        "Variables and data types",
        "Control flow",
        "Functions",
        "Lists and dictionaries",
        "Object-oriented programming",
        "Exceptions",
        "Modules and packages",
        "File handling",
    ],
    "DBMS": [
        "Relational model",
        "SQL queries",
        "Joins",
        "Keys and constraints",
        "Database normalization",
        "Transactions",
        "Indexes",
        "ER diagrams",
    ],
}
DIFFICULTIES = ("Beginner", "Intermediate", "Advanced")
QUESTION_COUNTS = (5, 10, 15)
QUIZ_PROMPT_SCHEMA_VERSION = "quiz-v2"
QUIZ_CACHE_TTL_SECONDS = 60 * 60
QUIZ_CACHE_MAX_ENTRIES = 128
_quiz_cache: dict[tuple[Any, ...], tuple[float, list[dict[str, Any]]]] = {}
_quiz_cache_lock = threading.Lock()
_quiz_cache_inflight: dict[tuple[Any, ...], Future[list[dict[str, Any]]]] = {}
_QUESTION_FIELDS = {
    "question",
    "concept",
    "options",
    "correct_option_index",
    "explanation",
    "subject",
    "topic",
    "difficulty",
}

QUIZ_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "questions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "question": {"type": "STRING"},
                    "concept": {"type": "STRING"},
                    "options": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "correct_option_index": {"type": "INTEGER"},
                    "explanation": {"type": "STRING"},
                    "subject": {"type": "STRING"},
                    "topic": {"type": "STRING"},
                    "difficulty": {"type": "STRING"},
                },
                "required": sorted(_QUESTION_FIELDS),
            },
        }
    },
    "required": ["questions"],
}


class QuizGenerationError(RuntimeError):
    """Raised when Gemini fails or returns quiz data that fails validation."""

    def __init__(self, message: str, provider_error: TutorServiceError | None = None) -> None:
        super().__init__(message)
        self.status_code = getattr(provider_error, "status_code", None)
        self.retry_delay_seconds = getattr(provider_error, "retry_delay_seconds", None)
        self.quota_scope = getattr(provider_error, "quota_scope", None)
        self.temporary_rate_limit = getattr(provider_error, "temporary_rate_limit", False)
        self.quota_type = getattr(provider_error, "quota_type", None)
        self.provider_model = getattr(provider_error, "provider_model", None)


_QUESTION_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "below", "by", "can", "choose",
    "consider", "do", "does", "for", "from", "given", "how", "identify", "in", "is",
    "it", "of", "on", "or", "please", "select", "suppose", "that", "the", "this",
    "to", "use", "using", "what", "when", "which", "why", "with", "you",
}
_GENERIC_CONCEPT_WORDS = {"concept", "example", "question", "topic", "understanding"}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in _tokens(text)
        if token not in _QUESTION_STOP_WORDS and token not in _GENERIC_CONCEPT_WORDS
    }


def _is_near_duplicate(first: str, second: str) -> bool:
    """Detect high lexical overlap while allowing shared subject vocabulary."""
    first_tokens = _content_tokens(first)
    second_tokens = _content_tokens(second)
    shared = first_tokens & second_tokens
    combined = first_tokens | second_tokens
    return len(shared) >= 4 and bool(combined) and len(shared) / len(combined) >= 0.82


def _question_pattern(question: str) -> str:
    """Classify broad wording format, not the subject matter of a question."""
    text = question.casefold().strip()
    words = _tokens(text)
    if "output" in words or "code" in words or "print" in words or "snippet" in words or "```" in text:
        return "code_or_output"
    if "complexity" in words or "big" in words and "o" in words:
        return "complexity_analysis"
    if words and words[0] in {"given", "suppose", "consider", "scenario"}:
        return "scenario_based"
    if words and words[0] in {"what", "which", "who"}:
        return "what_or_which"
    if words and words[0] == "how":
        return "how_to_or_application"
    if words and words[0] == "why":
        return "why_or_reasoning"
    return "other"


def _has_meaningful_explanation(explanation: Any) -> bool:
    """Reject blank, one-word, or effectively content-free explanations."""
    if not isinstance(explanation, str):
        return False
    words = _tokens(explanation)
    return len(explanation.strip()) >= 12 and len(words) >= 3


@measure_function("quiz.validate_response", provider="local", task="quiz")
def validate_quiz_payload(
    payload: Any,
    subject: str,
    topic: str,
    difficulty: str,
    question_count: int,
    *,
    allow_mixed_metadata: bool = False,
) -> list[dict[str, Any]]:
    """Validate the complete quiz response and normalize hidden answer data."""
    if subject not in SUBJECT_TOPICS or topic not in SUBJECT_TOPICS[subject]:
        raise QuizGenerationError("Choose a supported subject and topic.")
    if difficulty not in DIFFICULTIES:
        raise QuizGenerationError("Choose a supported difficulty.")
    if question_count not in QUESTION_COUNTS:
        raise QuizGenerationError("Question count must be 5, 10, or 15.")
    if not isinstance(payload, dict) or set(payload) != {"questions"}:
        raise QuizGenerationError("Gemini returned malformed quiz JSON.")

    raw_questions = payload["questions"]
    if not isinstance(raw_questions, list) or len(raw_questions) != question_count:
        raise QuizGenerationError(
            f"Gemini returned an incorrect question count; expected {question_count}. Generate the quiz again."
        )

    validated: list[dict[str, Any]] = []
    seen_questions: list[str] = []
    seen_concepts: list[str] = []
    question_patterns: dict[str, int] = {}
    for number, raw_question in enumerate(raw_questions, start=1):
        if not isinstance(raw_question, dict) or set(raw_question) != _QUESTION_FIELDS:
            raise QuizGenerationError(f"Question {number} is missing required fields or has unsupported fields.")

        question_text = raw_question["question"]
        concept = raw_question["concept"]
        explanation = raw_question["explanation"]
        options = raw_question["options"]
        if not isinstance(question_text, str) or not question_text.strip():
            raise QuizGenerationError(f"Question {number} has no question text.")
        if not isinstance(concept, str) or not _content_tokens(concept):
            raise QuizGenerationError(f"Question {number} has no meaningful concept label.")
        if not _has_meaningful_explanation(explanation):
            raise QuizGenerationError(f"Question {number} has a missing or empty explanation.")
        if not isinstance(options, list) or len(options) != 4:
            raise QuizGenerationError(f"Question {number} must have exactly four answer options.")
        if any(not isinstance(option, str) or not option.strip() for option in options):
            raise QuizGenerationError(f"Question {number} has an empty or invalid answer option.")
        normalized_options = [option.strip() for option in options]
        if len({option.casefold() for option in normalized_options}) != 4:
            raise QuizGenerationError(f"Question {number} has duplicate answer options.")

        correct_index = raw_question["correct_option_index"]
        if type(correct_index) is not int or correct_index not in range(4):
            raise QuizGenerationError(f"Question {number} has an invalid correct answer index.")
        if raw_question["subject"] != subject:
            raise QuizGenerationError(f"Question {number} does not match the selected subject.")
        if allow_mixed_metadata:
            if raw_question["topic"] not in SUBJECT_TOPICS[subject]:
                raise QuizGenerationError(f"Question {number} uses an unavailable subject topic.")
            if raw_question["difficulty"] not in DIFFICULTIES:
                raise QuizGenerationError(f"Question {number} uses an unavailable difficulty.")
        else:
            if raw_question["topic"] != topic:
                raise QuizGenerationError(f"Question {number} does not match the selected topic.")
            if raw_question["difficulty"] != difficulty:
                raise QuizGenerationError(f"Question {number} does not match the selected difficulty.")

        normalized_question = question_text.strip()
        normalized_key = " ".join(_tokens(normalized_question))
        for previous_question in seen_questions:
            previous_key = " ".join(_tokens(previous_question))
            if normalized_key == previous_key:
                raise QuizGenerationError(f"Question {number} duplicates another question.")
            if _is_near_duplicate(normalized_question, previous_question):
                raise QuizGenerationError(f"Question {number} is too similar in wording to another question.")

        concept_text = concept.strip()
        concept_key = " ".join(sorted(_content_tokens(concept_text)))
        for previous_concept in seen_concepts:
            previous_key = " ".join(sorted(_content_tokens(previous_concept)))
            if concept_key == previous_key or _is_near_duplicate(concept_text, previous_concept):
                raise QuizGenerationError(f"Question {number} repeats an underlying concept.")

        seen_questions.append(normalized_question)
        seen_concepts.append(concept_text)
        pattern = _question_pattern(normalized_question)
        question_patterns[pattern] = question_patterns.get(pattern, 0) + 1
        validated.append(
            {
                "question": normalized_question,
                "concept": concept_text,
                "options": normalized_options,
                "correct_option_index": correct_index,
                "correct_answer": normalized_options[correct_index],
                "explanation": explanation.strip(),
                "subject": subject,
                "topic": raw_question["topic"] if allow_mixed_metadata else topic,
                "difficulty": raw_question["difficulty"] if allow_mixed_metadata else difficulty,
            }
        )
    pattern_limit = max(2, math.ceil(question_count * 0.6))
    if max(question_patterns.values(), default=0) > pattern_limit:
        raise QuizGenerationError("Quiz uses the same question wording pattern too often. Generate it again for broader variety.")
    return validated


def build_quiz_prompt(subject: str, topic: str, difficulty: str, question_count: int) -> str:
    """Build explicit authoring instructions; the schema enforces JSON structure."""
    return f"""Create exactly {question_count} original multiple-choice questions for a university student.
Subject code: {subject}
Topic: {topic}
Difficulty: {difficulty}

Make each question clear, technically accurate, appropriately challenging for
the selected difficulty, and unambiguous. Each must have four distinct plausible
options and exactly one defensible correct option. Set correct_option_index to
an integer from 0 to 3 inclusive; never encode it as a string. Every explanation
 must teach why the answer is correct in one or two concise sentences, without
 repeating the question or adding filler. Set subject, topic, and difficulty on each
item to exactly the values above.

Cover different concepts within the selected topic. Provide a concise canonical
concept label for every question; use the same label for the same underlying
concept and distinct labels for different concepts. Do not test the same concept
twice or superficially reword an earlier question. Vary question formats across
conceptual understanding, practical application, code/output interpretation,
complexity analysis, and scenario-based reasoning where relevant to this topic.
Avoid ambiguous wording and trick questions. Return only data matching the
provided JSON response schema."""


def _validate_generation_selection(subject: str, topic: str, difficulty: str, question_count: int) -> None:
    if subject not in SUBJECT_TOPICS or topic not in SUBJECT_TOPICS.get(subject, []):
        raise QuizGenerationError("Choose a supported subject and topic.")
    if difficulty not in DIFFICULTIES:
        raise QuizGenerationError("Choose Beginner, Intermediate, or Advanced difficulty.")
    if question_count not in QUESTION_COUNTS:
        raise QuizGenerationError("Question count must be 5, 10, or 15.")


def _generate_quiz_uncached(subject: str, topic: str, difficulty: str, question_count: int) -> list[dict[str, Any]]:
    """Make one structured generation request and validate it before returning."""
    model = get_gemini_model()
    with measure_stage("quiz.prompt_construction", provider="local", model=model, task="quiz"):
        prompt = build_quiz_prompt(subject, topic, difficulty, question_count)
    try:
        response_text = generate_structured_content(
            prompt,
            QUIZ_RESPONSE_SCHEMA,
        )
    except TutorServiceError as error:
        raise QuizGenerationError(str(error), provider_error=error) from None
    try:
        with measure_stage("quiz.response_parsing", provider="gemini", model=model, task="quiz"):
            payload = json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        raise QuizGenerationError("Gemini returned invalid JSON. No quiz was created; please try again.") from None
    with measure_stage("quiz.validation", provider="local", model=model, task="quiz"):
        return validate_quiz_payload(payload, subject, topic, difficulty, question_count)


def clear_quiz_cache() -> None:
    """Clear process-local cached quiz content (primarily useful for tests)."""
    with _quiz_cache_lock:
        _quiz_cache.clear()


def _quiz_cache_key(subject: str, topic: str, difficulty: str, question_count: int) -> tuple[Any, ...]:
    return (subject, topic, difficulty, question_count, QUIZ_PROMPT_SCHEMA_VERSION)


@measure_function("quiz.generate_total", provider="cache_or_gemini", task="quiz")
def generate_quiz(
    subject: str,
    topic: str,
    difficulty: str,
    question_count: int,
    *,
    force_new: bool = False,
) -> list[dict[str, Any]]:
    """Generate a validated quiz, reusing generic successful content unless fresh is requested."""
    _validate_generation_selection(subject, topic, difficulty, question_count)
    key = _quiz_cache_key(subject, topic, difficulty, question_count)
    now = time.monotonic()

    if force_new:
        questions = _generate_quiz_uncached(subject, topic, difficulty, question_count)
        with _quiz_cache_lock:
            _quiz_cache[key] = (time.monotonic(), deepcopy(questions))
            _trim_quiz_cache_locked()
        return deepcopy(questions)

    record_quiz_cache_lookup()

    with _quiz_cache_lock:
        cached = _quiz_cache.get(key)
        if cached and now - cached[0] < QUIZ_CACHE_TTL_SECONDS:
            record_cached_quiz_retrieval()
            return deepcopy(cached[1])
        if cached:
            _quiz_cache.pop(key, None)
        future = _quiz_cache_inflight.get(key)
        is_owner = future is None
        if is_owner:
            future = Future()
            _quiz_cache_inflight[key] = future

    if not is_owner:
        # Concurrent identical reruns share the one in-flight provider request.
        record_cached_quiz_retrieval()
        return deepcopy(future.result())

    try:
        questions = _generate_quiz_uncached(subject, topic, difficulty, question_count)
        with _quiz_cache_lock:
            _quiz_cache[key] = (time.monotonic(), deepcopy(questions))
            _trim_quiz_cache_locked()
        future.set_result(deepcopy(questions))
        return deepcopy(questions)
    except Exception as error:
        future.set_exception(error)
        raise
    finally:
        with _quiz_cache_lock:
            _quiz_cache_inflight.pop(key, None)


def _trim_quiz_cache_locked() -> None:
    now = time.monotonic()
    expired = [key for key, (created, _questions) in _quiz_cache.items() if now - created >= QUIZ_CACHE_TTL_SECONDS]
    for key in expired:
        _quiz_cache.pop(key, None)
    while len(_quiz_cache) > QUIZ_CACHE_MAX_ENTRIES:
        oldest = min(_quiz_cache, key=lambda cache_key: _quiz_cache[cache_key][0])
        _quiz_cache.pop(oldest, None)


def evaluate_answers(questions: Sequence[dict[str, Any]], answers: Sequence[int | None]) -> dict[str, Any]:
    """Score selected option indexes deterministically and return review details."""
    if not questions or len(answers) != len(questions):
        raise ValueError("Answers must match a non-empty question list.")
    correct = incorrect = unanswered = 0
    review: list[dict[str, Any]] = []
    for number, (question, selected_index) in enumerate(zip(questions, answers), start=1):
        explanation = question.get("explanation")
        if not _has_meaningful_explanation(explanation):
            raise ValueError(f"Question {number} has no valid explanation to review.")
        correct_index = question["correct_option_index"]
        correct_answer = question["options"][correct_index]
        if selected_index is None:
            unanswered += 1
            is_correct = False
            selected_answer = None
        else:
            if type(selected_index) is not int or selected_index not in range(4):
                raise ValueError("A selected answer index is invalid.")
            selected_answer = question["options"][selected_index]
            is_correct = selected_index == correct_index
            if is_correct:
                correct += 1
            else:
                incorrect += 1
        review.append(
            {
                "question_number": number,
                "question": question["question"],
                "options": list(question["options"]),
                "selected_answer": selected_answer,
                "correct_answer": correct_answer,
                "explanation": explanation.strip(),
                "is_correct": is_correct,
            }
        )
    total = len(questions)
    return {
        "total_questions": total,
        "correct_answers": correct,
        "incorrect_answers": incorrect,
        "unanswered_questions": unanswered,
        "score_percentage": round(correct * 100 / total, 2),
        "review": review,
    }


def submit_quiz(
    student_id: int,
    quiz_state: dict[str, Any],
    *,
    diagnostic_data: dict[str, object] | None = None,
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate and persist one quiz exactly once for its owning student."""
    if quiz_state.get("student_id") != student_id:
        raise PermissionError("This quiz does not belong to the signed-in student.")
    if quiz_state.get("submitted"):
        evaluation = quiz_state.get("evaluation")
        if evaluation is None:
            raise RuntimeError("Quiz was marked submitted without a saved result.")
        return evaluation

    questions = quiz_state.get("questions")
    answers = quiz_state.get("answers")
    if not isinstance(questions, list) or not isinstance(answers, list):
        raise ValueError("Quiz data is incomplete.")
    evaluation = evaluation or evaluate_answers(questions, answers)
    responses = []
    for number, (question, review) in enumerate(zip(questions, evaluation["review"]), start=1):
        concept = question.get("concept")
        if not isinstance(concept, str) or not concept.strip():
            concept = None
        topic = question.get("topic") or quiz_state["topic"]
        responses.append({
            "question_id": f"q{number:04d}",
            "subject": quiz_state["subject"],
            "topic": topic,
            "difficulty": question.get("difficulty") or quiz_state["difficulty"],
            "concept": concept,
            "selected_answer": review["selected_answer"],
            "correct_answer": review["correct_answer"],
            # Unanswered questions are persisted but excluded from concept
            # attempt/accuracy calculations.
            "is_correct": review["is_correct"] if review["selected_answer"] is not None else None,
        })
    attempt_id = save_quiz_attempt(
        student_id=student_id,
        subject=quiz_state["subject"],
        topic=quiz_state["topic"],
        difficulty=quiz_state["difficulty"],
        total_questions=evaluation["total_questions"],
        correct_answers=evaluation["correct_answers"],
        score_percentage=evaluation["score_percentage"],
        attempt_key=quiz_state["attempt_key"],
        responses=responses,
        diagnostic=diagnostic_data,
    )
    quiz_state["evaluation"] = evaluation
    quiz_state["attempt_id"] = attempt_id
    quiz_state["submitted"] = True
    return evaluation
