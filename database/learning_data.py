"""Efficient student-scoped queries for concept and subject performance."""

import streamlit as st

from database import db as database
from database.db import get_connection
from utils.performance import measure_function


@st.cache_data(ttl=60, show_spinner=False)
def _cached_learning_data_snapshot(
    student_id: int,
    database_path: str,
    database_signature: tuple[int, int] | None,
) -> dict[str, list[dict[str, object]]]:
    """Cache a student-scoped snapshot for one database version."""
    del database_path, database_signature  # Values deliberately participate in Streamlit's cache key.
    return _query_learning_data_snapshot(student_id)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_dashboard_overview(
    student_id: int,
    database_path: str,
    database_signature: tuple[int, int] | None,
) -> dict[str, object]:
    del database_path, database_signature
    overview = database.get_dashboard_overview(student_id)
    return {
        "stats": dict(overview["stats"]),
        "progress": [dict(row) for row in overview["progress"]],
        "recent_attempts": [dict(row) for row in overview["recent_attempts"]],
        "subject_quiz_stats": [dict(row) for row in overview["subject_quiz_stats"]],
    }


def _database_cache_key() -> tuple[str, tuple[int, int] | None]:
    path = database.DATABASE_PATH
    try:
        file_stat = path.stat()
        signature = (file_stat.st_mtime_ns, file_stat.st_size)
    except OSError:
        signature = None
    return str(path.resolve()), signature


@measure_function("database.get_learning_data_snapshot")
def get_learning_data_snapshot(student_id: int) -> dict[str, list[dict[str, object]]]:
    """Return a cached snapshot for this student and current SQLite file version."""
    database_path, signature = _database_cache_key()
    return _cached_learning_data_snapshot(student_id, database_path, signature)


@measure_function("database.get_cached_dashboard_overview")
def get_cached_dashboard_overview(student_id: int) -> dict[str, object]:
    """Return a student-scoped dashboard overview for the current database version."""
    database_path, signature = _database_cache_key()
    return _cached_dashboard_overview(student_id, database_path, signature)


def clear_learning_data_snapshot_cache() -> None:
    """Invalidate cached learning and dashboard data after this process changes records."""
    _cached_learning_data_snapshot.clear()
    _cached_dashboard_overview.clear()


@measure_function("database.query_learning_data_snapshot")
def _query_learning_data_snapshot(student_id: int) -> dict[str, list[dict[str, object]]]:
    """Build aggregate rows and a bounded recent-attempt window for one student."""
    connection = get_connection()
    try:
        subjects = connection.execute(
            """
            SELECT subject, COUNT(*) AS quiz_count,
                   COALESCE(SUM(total_questions), 0) AS total_questions,
                   COALESCE(SUM(correct_answers), 0) AS correct_answers,
                   MAX(id) AS latest_attempt_id
            FROM quiz_attempts
            WHERE student_id = ?
            GROUP BY subject
            ORDER BY subject
            """,
            (student_id,),
        ).fetchall()

        concepts = connection.execute(
            """
            WITH labeled AS (
                SELECT subject, TRIM(topic) AS topic, TRIM(concept) AS concept,
                       selected_answer, is_correct, answered_at, id
                FROM quiz_responses
                WHERE student_id = ? AND topic IS NOT NULL AND TRIM(topic) <> ''
                  AND concept IS NOT NULL AND TRIM(concept) <> ''
            ), ranked AS (
                SELECT subject, topic, concept, selected_answer, is_correct,
                       ROW_NUMBER() OVER (
                           PARTITION BY subject, topic, concept
                           ORDER BY answered_at DESC, id DESC
                       ) AS recent_rank
                FROM labeled
                WHERE selected_answer IS NOT NULL AND is_correct IS NOT NULL
            )
            SELECT subject, topic, concept,
                   COUNT(*) AS attempted,
                   SUM(is_correct) AS correct,
                   SUM(CASE WHEN recent_rank <= 5 THEN 1 ELSE 0 END) AS recent_attempted,
                   SUM(CASE WHEN recent_rank <= 5 THEN is_correct ELSE 0 END) AS recent_correct
            FROM ranked
            GROUP BY subject, topic, concept
            ORDER BY subject, topic, concept
            """,
            (student_id,),
        ).fetchall()

        topics = connection.execute(
            """
            WITH labeled AS (
                SELECT subject, TRIM(topic) AS topic, selected_answer, is_correct,
                       answered_at, id
                FROM quiz_responses
                WHERE student_id = ? AND topic IS NOT NULL AND TRIM(topic) <> ''
            ), ranked AS (
                SELECT subject, topic, selected_answer, is_correct,
                       ROW_NUMBER() OVER (
                           PARTITION BY subject, topic
                           ORDER BY answered_at DESC, id DESC
                       ) AS recent_rank
                FROM labeled
                WHERE selected_answer IS NOT NULL AND is_correct IS NOT NULL
            )
            SELECT subject, topic, COUNT(*) AS attempted,
                   SUM(is_correct) AS correct,
                   SUM(CASE WHEN recent_rank <= 5 THEN 1 ELSE 0 END) AS recent_attempted,
                   SUM(CASE WHEN recent_rank <= 5 THEN is_correct ELSE 0 END) AS recent_correct
            FROM ranked
            GROUP BY subject, topic
            ORDER BY subject, topic
            """,
            (student_id,),
        ).fetchall()

        response_metadata = connection.execute(
            """
            SELECT subject, COUNT(*) AS response_count,
                   SUM(CASE WHEN concept IS NULL OR TRIM(concept) = '' THEN 1 ELSE 0 END)
                       AS missing_concept_count
            FROM quiz_responses
            WHERE student_id = ?
            GROUP BY subject
            ORDER BY subject
            """,
            (student_id,),
        ).fetchall()

        recent_attempts = connection.execute(
            """
            WITH ranked AS (
                SELECT subject, topic, difficulty, total_questions, score, completed_at, id,
                       ROW_NUMBER() OVER (
                           PARTITION BY subject ORDER BY completed_at DESC, id DESC
                       ) AS recent_rank
                FROM quiz_attempts
                WHERE student_id = ?
            )
            SELECT subject, topic, difficulty, total_questions, score,
                   completed_at, id, recent_rank
            FROM ranked
            WHERE recent_rank <= 10
            ORDER BY subject, recent_rank
            """,
            (student_id,),
        ).fetchall()
        return {
            "subjects": [dict(row) for row in subjects],
            "concepts": [dict(row) for row in concepts],
            "topics": [dict(row) for row in topics],
            "response_metadata": [dict(row) for row in response_metadata],
            "recent_attempts": [dict(row) for row in recent_attempts],
        }
    finally:
        connection.close()


@measure_function("database.get_latest_diagnostic_assessment")
def get_latest_diagnostic_assessment(student_id: int, subject: str) -> dict[str, object] | None:
    """Return the latest diagnostic result for one authenticated student and subject."""
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT d.attempt_id, d.self_assessed_proficiency,
                   d.demonstrated_proficiency, d.assessment_status,
                   d.answered_questions, d.accuracy, d.created_at,
                   d.provider, d.task, d.input_tokens, d.output_tokens, d.fallback_used,
                   a.score, a.total_questions
            FROM diagnostic_assessments AS d
            JOIN quiz_attempts AS a ON a.id = d.attempt_id AND a.student_id = d.student_id
            WHERE d.student_id = ? AND a.subject = ?
            ORDER BY d.created_at DESC, d.id DESC LIMIT 1
            """,
            (student_id, subject),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


@measure_function("database.get_latest_topic_practice_difficulty")
def get_latest_topic_practice_difficulty(student_id: int, subject: str, topic: str) -> str | None:
    """Get the latest non-diagnostic difficulty for one student's topic."""
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT difficulty FROM quiz_attempts
            WHERE student_id = ? AND subject = ? AND topic = ?
              AND topic <> 'Initial diagnostic'
            ORDER BY completed_at DESC, id DESC LIMIT 1
            """,
            (student_id, subject, topic),
        ).fetchone()
        return str(row["difficulty"]) if row and row["difficulty"] in ("Beginner", "Intermediate", "Advanced") else None
    finally:
        connection.close()


@measure_function("database.get_latest_topic_concept")
def get_latest_topic_concept(student_id: int, subject: str, topic: str) -> str | None:
    """Return the latest answered, non-empty concept for one student's subject/topic."""
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT concept FROM quiz_responses
            WHERE student_id = ? AND subject = ? AND topic = ?
              AND selected_answer IS NOT NULL
              AND concept IS NOT NULL AND TRIM(concept) <> ''
            ORDER BY answered_at DESC, id DESC LIMIT 1
            """,
            (student_id, subject, topic),
        ).fetchone()
        return str(row["concept"]).strip() if row else None
    finally:
        connection.close()


@measure_function("database.get_current_adaptive_recommendation")
def get_current_adaptive_recommendation(student_id: int, subject: str) -> dict[str, object] | None:
    """Return a non-stale recommendation only when its source attempt is current."""
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT r.payload_json, r.source_attempt_id, r.provider, r.task,
                   r.input_tokens, r.output_tokens, r.fallback_used, r.generated_at,
                   (SELECT MAX(a.id) FROM quiz_attempts AS a
                    WHERE a.student_id = r.student_id AND a.subject = r.subject) AS latest_attempt_id
            FROM adaptive_recommendations AS r
            WHERE r.student_id = ? AND r.subject = ? AND r.status = 'current'
            """,
            (student_id, subject),
        ).fetchone()
        if not row or row["source_attempt_id"] != row["latest_attempt_id"]:
            return None
        return dict(row)
    finally:
        connection.close()


@measure_function("database.save_adaptive_recommendation")
def save_adaptive_recommendation(
    student_id: int,
    subject: str,
    payload_json: str,
    source_attempt_id: int | None,
    *,
    provider: str,
    task: str,
    input_tokens: int | None,
    output_tokens: int | None,
    fallback_used: bool,
) -> None:
    """Upsert a student's structured recommendation and guard against stale races."""
    connection = get_connection()
    try:
        latest = connection.execute(
            "SELECT MAX(id) FROM quiz_attempts WHERE student_id = ? AND subject = ?",
            (student_id, subject),
        ).fetchone()[0]
        status = "current" if latest == source_attempt_id else "stale"
        connection.execute(
            """
            INSERT INTO adaptive_recommendations
                (student_id, subject, payload_json, source_attempt_id, provider, task,
                 input_tokens, output_tokens, fallback_used, status, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id, subject) DO UPDATE SET
                payload_json = excluded.payload_json,
                source_attempt_id = excluded.source_attempt_id,
                provider = excluded.provider,
                task = excluded.task,
                input_tokens = excluded.input_tokens,
                output_tokens = excluded.output_tokens,
                fallback_used = excluded.fallback_used,
                status = excluded.status,
                generated_at = CURRENT_TIMESTAMP
            """,
            (student_id, subject, payload_json, source_attempt_id, provider, task,
             input_tokens, output_tokens, int(fallback_used), status),
        )
        connection.commit()
    finally:
        connection.close()
