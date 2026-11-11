"""SQLite/PostgreSQL connection, schema, and student-specific data queries."""

import hashlib
import sqlite3
import threading
from pathlib import Path
from typing import Any

import psycopg

from utils.config import DATABASE_PATH, get_database_url
from utils.performance import measure_function

_initialized_paths: set[str] = set()
_initialization_lock = threading.Lock()
LEARNING_SCHEMA_VERSION = 3
POSTGRES_SCHEMA_VERSION = 1


class DatabaseConnectionError(RuntimeError):
    """Redacted error for PostgreSQL connection failures."""


DATABASE_ERRORS = (sqlite3.Error, psycopg.Error, DatabaseConnectionError)
INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)


class DatabaseRow:
    """Provide sqlite.Row-style named and positional access for PostgreSQL results."""

    __slots__ = ("_names", "_values", "_positions")

    def __init__(self, names: tuple[str, ...], values: tuple[Any, ...]) -> None:
        self._names = names
        self._values = values
        self._positions = {name: index for index, name in enumerate(names)}

    def __getitem__(self, key: str | int | slice) -> Any:
        if isinstance(key, str):
            return self._values[self._positions[key]]
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def keys(self) -> tuple[str, ...]:
        return self._names


DatabaseRowLike = sqlite3.Row | DatabaseRow


class PostgresConnection:
    """Adapt qmark SQL and batch execution to Psycopg without changing callers."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    @staticmethod
    def _format_query(query: str) -> str:
        return query.replace("?", "%s")

    def execute(self, query: str, params: tuple[Any, ...] = ()):
        return self._connection.execute(self._format_query(query), params)

    def cursor(self, *args: Any, **kwargs: Any):
        return PostgresCursor(self._connection.cursor(*args, **kwargs))

    def executemany(self, query: str, params: list[tuple[Any, ...]]) -> None:
        with self.cursor() as cursor:
            cursor.executemany(self._format_query(query), params)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class PostgresCursor:
    """Keep the familiar cursor API while translating SQLite-style placeholders."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def execute(self, query: str, params: tuple[Any, ...] = ()):
        self._cursor.execute(PostgresConnection._format_query(query), params)
        return self

    def executemany(self, query: str, params: list[tuple[Any, ...]]):
        self._cursor.executemany(PostgresConnection._format_query(query), params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchmany(self, size: int | None = None):
        return self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self) -> None:
        self._cursor.close()

    def __iter__(self):
        return iter(self._cursor)

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, *args: Any):
        return self._cursor.__exit__(*args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


def _postgres_row_factory(cursor: Any):
    """Create rows that support both named and positional indexing."""
    return lambda values: DatabaseRow(
        tuple(column.name for column in cursor.description), values
    )


def get_database_backend() -> str:
    """Select PostgreSQL when configured; otherwise retain the SQLite backend."""
    return "postgresql" if get_database_url() else "sqlite"


@measure_function("database.open_connection")
def get_connection():
    """Open a connection using DATABASE_URL or the local SQLite fallback."""
    database_url = get_database_url()
    if database_url:
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://"):]
        if not database_url.startswith("postgresql://"):
            raise ValueError("DATABASE_URL must use a PostgreSQL connection URL.")
        try:
            connection = psycopg.connect(database_url, row_factory=_postgres_row_factory)
        except psycopg.Error as error:
            raise DatabaseConnectionError(
                f"Could not connect to the configured PostgreSQL database "
                f"({type(error).__name__}). Check DATABASE_URL and network access."
            ) from None
        return PostgresConnection(connection)

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@measure_function("database.initialize_schema")
def initialize_database() -> None:
    """Create authentication and learning tables, migrating the starter table."""
    database_url = get_database_url()
    database_key = (
        "postgresql:" + hashlib.sha256(database_url.encode("utf-8")).hexdigest()
        if database_url
        else str(Path(DATABASE_PATH).resolve())
    )
    with _initialization_lock:
        if database_key in _initialized_paths:
            return
        _initialize_database_schema()
        _initialized_paths.add(database_key)


def _initialize_database_schema() -> None:
    """Create the base schema and apply additive, versioned migrations."""
    if get_database_url():
        _initialize_postgresql_schema()
        return

    connection = get_connection()
    try:
        current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version > LEARNING_SCHEMA_VERSION:
            raise RuntimeError("Database schema version is newer than this application supports.")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT NOT NULL,
                email TEXT,
                password_hash TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Existing scaffold databases may already have students without credentials.
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(students)")}
        if "email" not in columns:
            connection.execute("ALTER TABLE students ADD COLUMN email TEXT")
        if "password_hash" not in columns:
            connection.execute("ALTER TABLE students ADD COLUMN password_hash TEXT")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_students_email ON students(email) "
            "WHERE email IS NOT NULL"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                subject TEXT NOT NULL,
                topic TEXT NOT NULL,
                progress_percent REAL NOT NULL DEFAULT 0 CHECK(progress_percent BETWEEN 0 AND 100),
                status TEXT NOT NULL DEFAULT 'in_progress',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(student_id, subject, topic)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                subject TEXT NOT NULL,
                topic TEXT NOT NULL,
                score REAL NOT NULL CHECK(score BETWEEN 0 AND 100),
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Extend the existing attempts table in place; preserve all older rows.
        attempt_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(quiz_attempts)")
        }
        if "difficulty" not in attempt_columns:
            connection.execute(
                "ALTER TABLE quiz_attempts ADD COLUMN difficulty TEXT NOT NULL DEFAULT 'Intermediate'"
            )
        if "total_questions" not in attempt_columns:
            connection.execute(
                "ALTER TABLE quiz_attempts ADD COLUMN total_questions INTEGER NOT NULL DEFAULT 0 CHECK(total_questions >= 0)"
            )
        if "correct_answers" not in attempt_columns:
            connection.execute(
                "ALTER TABLE quiz_attempts ADD COLUMN correct_answers INTEGER NOT NULL DEFAULT 0 CHECK(correct_answers >= 0)"
            )
        if "attempt_key" not in attempt_columns:
            connection.execute("ALTER TABLE quiz_attempts ADD COLUMN attempt_key TEXT")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_quiz_attempt_student_key "
            "ON quiz_attempts(student_id, attempt_key) WHERE attempt_key IS NOT NULL"
        )
        if current_version < 1:
            # The composite key lets SQLite enforce that a response belongs to
            # an attempt owned by the same student_id stored on the response.
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_quiz_attempt_id_student "
                "ON quiz_attempts(id, student_id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS quiz_responses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    attempt_id INTEGER NOT NULL,
                    question_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    concept TEXT,
                    selected_answer TEXT,
                    correct_answer TEXT NOT NULL,
                    is_correct INTEGER CHECK(is_correct IN (0, 1) OR is_correct IS NULL),
                    answered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(attempt_id, question_id),
                    FOREIGN KEY (attempt_id, student_id)
                        REFERENCES quiz_attempts(id, student_id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_quiz_responses_student_subject_concept "
                "ON quiz_responses(student_id, subject, concept, answered_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_quiz_responses_student_attempt "
                "ON quiz_responses(student_id, attempt_id)"
            )
            connection.execute("PRAGMA user_version = 1")
        if current_version < 2:
            response_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(quiz_responses)")
            }
            if "difficulty" not in response_columns:
                connection.execute("ALTER TABLE quiz_responses ADD COLUMN difficulty TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS diagnostic_assessments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    attempt_id INTEGER NOT NULL UNIQUE,
                    self_assessed_proficiency TEXT NOT NULL
                        CHECK(self_assessed_proficiency IN ('Beginner', 'Intermediate', 'Advanced', 'Not sure')),
                    demonstrated_proficiency TEXT NOT NULL,
                    assessment_status TEXT NOT NULL CHECK(assessment_status IN ('assessed', 'insufficient_evidence')),
                    answered_questions INTEGER NOT NULL CHECK(answered_questions >= 0),
                    accuracy REAL CHECK(accuracy BETWEEN 0 AND 100 OR accuracy IS NULL),
                    provider TEXT NOT NULL,
                    task TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    fallback_used INTEGER NOT NULL CHECK(fallback_used IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (attempt_id, student_id)
                        REFERENCES quiz_attempts(id, student_id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_diagnostic_student_subject "
                "ON diagnostic_assessments(student_id, created_at DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS adaptive_recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    subject TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source_attempt_id INTEGER,
                    provider TEXT NOT NULL,
                    task TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    fallback_used INTEGER NOT NULL CHECK(fallback_used IN (0, 1)),
                    status TEXT NOT NULL CHECK(status IN ('current', 'stale')),
                    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(student_id, subject),
                    FOREIGN KEY (source_attempt_id, student_id)
                        REFERENCES quiz_attempts(id, student_id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_recommendation_student_status "
                "ON adaptive_recommendations(student_id, status, subject)"
            )
            connection.execute("PRAGMA user_version = 2")
        if current_version < 3:
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_quiz_attempts_student_subject_topic_completed "
                "ON quiz_attempts(student_id, subject, topic, completed_at DESC, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_quiz_responses_student_subject_topic_recent "
                "ON quiz_responses(student_id, subject, topic, answered_at DESC, id DESC)"
            )
            connection.execute("PRAGMA user_version = 3")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@measure_function("database.initialize_postgresql_schema")
def _initialize_postgresql_schema() -> None:
    """Create the PostgreSQL schema transactionally, serializing concurrent startup."""
    connection = get_connection()
    try:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (71949290117661,))
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
                    DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
            )
            """
        )
        current_version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
        if current_version > POSTGRES_SCHEMA_VERSION:
            raise RuntimeError("Database schema version is newer than this application supports.")

        if current_version < 1:
            statements = (
                """
                CREATE TABLE IF NOT EXISTS students (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    email TEXT,
                    password_hash TEXT,
                    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
                        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS learning_progress (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    subject TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    progress_percent DOUBLE PRECISION NOT NULL DEFAULT 0
                        CHECK(progress_percent BETWEEN 0 AND 100),
                    status TEXT NOT NULL DEFAULT 'in_progress',
                    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
                        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                    UNIQUE(student_id, subject, topic)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS quiz_attempts (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    subject TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    score DOUBLE PRECISION NOT NULL CHECK(score BETWEEN 0 AND 100),
                    completed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
                        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                    difficulty TEXT NOT NULL DEFAULT 'Intermediate',
                    total_questions INTEGER NOT NULL DEFAULT 0 CHECK(total_questions >= 0),
                    correct_answers INTEGER NOT NULL DEFAULT 0 CHECK(correct_answers >= 0),
                    attempt_key TEXT,
                    CONSTRAINT idx_quiz_attempt_id_student UNIQUE (id, student_id)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS quiz_responses (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    attempt_id BIGINT NOT NULL,
                    question_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    concept TEXT,
                    selected_answer TEXT,
                    correct_answer TEXT NOT NULL,
                    is_correct SMALLINT CHECK(is_correct IN (0, 1) OR is_correct IS NULL),
                    answered_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
                        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                    difficulty TEXT,
                    UNIQUE(attempt_id, question_id),
                    FOREIGN KEY (attempt_id, student_id)
                        REFERENCES quiz_attempts(id, student_id) ON DELETE CASCADE
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS diagnostic_assessments (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    attempt_id BIGINT NOT NULL UNIQUE,
                    self_assessed_proficiency TEXT NOT NULL
                        CHECK(self_assessed_proficiency IN ('Beginner', 'Intermediate', 'Advanced', 'Not sure')),
                    demonstrated_proficiency TEXT NOT NULL,
                    assessment_status TEXT NOT NULL
                        CHECK(assessment_status IN ('assessed', 'insufficient_evidence')),
                    answered_questions INTEGER NOT NULL CHECK(answered_questions >= 0),
                    accuracy DOUBLE PRECISION CHECK(accuracy BETWEEN 0 AND 100 OR accuracy IS NULL),
                    provider TEXT NOT NULL,
                    task TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    fallback_used SMALLINT NOT NULL CHECK(fallback_used IN (0, 1)),
                    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
                        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                    FOREIGN KEY (attempt_id, student_id)
                        REFERENCES quiz_attempts(id, student_id) ON DELETE CASCADE
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS adaptive_recommendations (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    subject TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source_attempt_id BIGINT,
                    provider TEXT NOT NULL,
                    task TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    fallback_used SMALLINT NOT NULL CHECK(fallback_used IN (0, 1)),
                    status TEXT NOT NULL CHECK(status IN ('current', 'stale')),
                    generated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
                        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                    UNIQUE(student_id, subject),
                    FOREIGN KEY (source_attempt_id, student_id)
                        REFERENCES quiz_attempts(id, student_id) ON DELETE CASCADE
                )
                """,
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_students_email "
                "ON students(email) WHERE email IS NOT NULL",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_quiz_attempt_student_key "
                "ON quiz_attempts(student_id, attempt_key) WHERE attempt_key IS NOT NULL",
                "CREATE INDEX IF NOT EXISTS idx_quiz_responses_student_subject_concept "
                "ON quiz_responses(student_id, subject, concept, answered_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_quiz_responses_student_attempt "
                "ON quiz_responses(student_id, attempt_id)",
                "CREATE INDEX IF NOT EXISTS idx_diagnostic_student_subject "
                "ON diagnostic_assessments(student_id, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_recommendation_student_status "
                "ON adaptive_recommendations(student_id, status, subject)",
                "CREATE INDEX IF NOT EXISTS idx_quiz_attempts_student_subject_topic_completed "
                "ON quiz_attempts(student_id, subject, topic, completed_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_quiz_responses_student_subject_topic_recent "
                "ON quiz_responses(student_id, subject, topic, answered_at DESC, id DESC)",
            )
            for statement in statements:
                connection.execute(statement)
            connection.execute("INSERT INTO schema_migrations (version) VALUES (1)")

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@measure_function("database.get_dashboard_overview")
def get_dashboard_overview(student_id: int) -> dict[str, object]:
    """Load all dashboard data with one short-lived connection for one student."""
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM learning_progress WHERE student_id = ? AND progress_percent > 0) AS topics_studied,
                (SELECT COUNT(*) FROM quiz_attempts WHERE student_id = ?) AS quizzes_completed,
                (SELECT AVG(score) FROM quiz_attempts WHERE student_id = ?) AS average_score,
                (SELECT AVG(progress_percent) FROM learning_progress WHERE student_id = ?) AS overall_progress,
                (SELECT SUM(total_questions) FROM quiz_attempts WHERE student_id = ?) AS questions_in_quizzes
            """,
            (student_id, student_id, student_id, student_id, student_id),
        ).fetchone()
        progress = connection.execute(
            "SELECT subject, topic, progress_percent, status, updated_at "
            "FROM learning_progress WHERE student_id = ? ORDER BY subject, topic",
            (student_id,),
        ).fetchall()
        recent_attempts = connection.execute(
            """
            SELECT id, subject, topic, difficulty, total_questions,
                   correct_answers, score, completed_at
            FROM quiz_attempts
            WHERE student_id = ?
            ORDER BY completed_at DESC, id DESC
            LIMIT 5
            """,
            (student_id,),
        ).fetchall()
        subject_stats = connection.execute(
            """
            SELECT subject, COUNT(*) AS attempts, AVG(score) AS average_score,
                   SUM(correct_answers) AS correct_answers,
                   SUM(total_questions) AS total_questions
            FROM quiz_attempts
            WHERE student_id = ?
            GROUP BY subject
            ORDER BY subject
            """,
            (student_id,),
        ).fetchall()
        return {
            "stats": {
                "topics_studied": row["topics_studied"],
                "quizzes_completed": row["quizzes_completed"],
                "average_score": row["average_score"],
                "overall_progress": row["overall_progress"],
                "questions_in_quizzes": row["questions_in_quizzes"] or 0,
            },
            "progress": progress,
            "recent_attempts": recent_attempts,
            "subject_quiz_stats": subject_stats,
        }
    finally:
        connection.close()


@measure_function("database.get_dashboard_stats")
def get_dashboard_stats(student_id: int) -> dict[str, int | float | None]:
    """Return actual aggregate learning data for one student only."""
    connection = get_connection()
    try:
        topics = connection.execute(
            "SELECT COUNT(*) FROM learning_progress WHERE student_id = ? AND progress_percent > 0",
            (student_id,),
        ).fetchone()[0]
        quiz = connection.execute(
            "SELECT COUNT(*) AS quiz_count, AVG(score) AS average_score "
            "FROM quiz_attempts WHERE student_id = ?",
            (student_id,),
        ).fetchone()
        progress = connection.execute(
            "SELECT AVG(progress_percent) FROM learning_progress WHERE student_id = ?",
            (student_id,),
        ).fetchone()[0]
        return {
            "topics_studied": topics,
            "quizzes_completed": quiz["quiz_count"],
            "average_score": quiz["average_score"],
            "overall_progress": progress,
        }
    finally:
        connection.close()


@measure_function("database.get_student_progress")
def get_student_progress(student_id: int) -> list[DatabaseRowLike]:
    """List a student's recorded topics, scoped by student ID."""
    connection = get_connection()
    try:
        return connection.execute(
            "SELECT subject, topic, progress_percent, status, updated_at "
            "FROM learning_progress WHERE student_id = ? ORDER BY subject, topic",
            (student_id,),
        ).fetchall()
    finally:
        connection.close()


@measure_function("database.save_quiz_attempt")
def save_quiz_attempt(
    student_id: int,
    subject: str,
    topic: str,
    difficulty: str,
    total_questions: int,
    correct_answers: int,
    score_percentage: float,
    attempt_key: str,
    responses: list[dict[str, object]] | None = None,
    diagnostic: dict[str, object] | None = None,
) -> int:
    """Persist a quiz result and its optional responses atomically and idempotently."""
    if total_questions < 1 or not 0 <= correct_answers <= total_questions:
        raise ValueError("Quiz totals are invalid.")
    if not 0 <= score_percentage <= 100 or not attempt_key.strip():
        raise ValueError("Quiz score or attempt key is invalid.")
    if score_percentage != round(correct_answers * 100 / total_questions, 2):
        raise ValueError("Quiz score must match the correct-answer total.")
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO quiz_attempts
                (student_id, subject, topic, difficulty, total_questions,
                 correct_answers, score, attempt_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(student_id, attempt_key) WHERE attempt_key IS NOT NULL DO NOTHING
            """,
            (
                student_id,
                subject,
                topic,
                difficulty,
                total_questions,
                correct_answers,
                score_percentage,
                attempt_key,
            ),
        )
        row = connection.execute(
            "SELECT id FROM quiz_attempts WHERE student_id = ? AND attempt_key = ?",
            (student_id, attempt_key),
        ).fetchone()
        if row is None:
            error_type = (
                psycopg.IntegrityError
                if get_database_backend() == "postgresql"
                else sqlite3.IntegrityError
            )
            raise error_type("Quiz attempt could not be saved for this student.")
        attempt_id = int(row["id"])
        if responses:
            response_rows = []
            for response in responses:
                question_id = response.get("question_id")
                response_subject = response.get("subject", subject)
                response_topic = response.get("topic", topic)
                response_difficulty = response.get("difficulty")
                correct = response.get("is_correct")
                if not isinstance(question_id, str) or not question_id.strip():
                    raise ValueError("Quiz response question ID is invalid.")
                if not isinstance(response_subject, str) or not response_subject.strip():
                    raise ValueError("Quiz response subject is invalid.")
                if not isinstance(response_topic, str) or not response_topic.strip():
                    raise ValueError("Quiz response topic is invalid.")
                if correct not in (None, True, False, 0, 1):
                    raise ValueError("Quiz response correctness is invalid.")
                response_rows.append((
                    student_id, attempt_id, question_id, response_subject, response_topic,
                    response.get("concept"), response.get("selected_answer"),
                    response.get("correct_answer"),
                    None if correct is None else int(bool(correct)),
                    response_difficulty,
                ))
            connection.executemany(
                """
                INSERT INTO quiz_responses
                    (student_id, attempt_id, question_id, subject, topic, concept,
                     selected_answer, correct_answer, is_correct, difficulty)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attempt_id, question_id) DO NOTHING
                """,
                response_rows,
            )
        if diagnostic is not None:
            self_assessed = diagnostic.get("self_assessed_proficiency")
            demonstrated = diagnostic.get("demonstrated_proficiency")
            status = diagnostic.get("assessment_status")
            answered = diagnostic.get("answered_questions")
            accuracy = diagnostic.get("accuracy")
            provider = diagnostic.get("provider", "unknown")
            task = diagnostic.get("task", "diagnostic")
            input_tokens = diagnostic.get("input_tokens")
            output_tokens = diagnostic.get("output_tokens")
            fallback_used = bool(diagnostic.get("fallback_used", False))
            if self_assessed not in ("Beginner", "Intermediate", "Advanced", "Not sure"):
                raise ValueError("Diagnostic self-assessment is invalid.")
            if not isinstance(demonstrated, str) or status not in ("assessed", "insufficient_evidence"):
                raise ValueError("Diagnostic result is invalid.")
            if type(answered) is not int or answered < 0:
                raise ValueError("Diagnostic answered-question count is invalid.")
            connection.execute(
                """
                INSERT INTO diagnostic_assessments
                    (student_id, attempt_id, self_assessed_proficiency,
                     demonstrated_proficiency, assessment_status, answered_questions, accuracy,
                     provider, task, input_tokens, output_tokens, fallback_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attempt_id) DO NOTHING
                """,
                (student_id, attempt_id, self_assessed, demonstrated, status, answered, accuracy,
                 provider, task, input_tokens, output_tokens, int(fallback_used)),
            )
        connection.execute(
            "UPDATE adaptive_recommendations SET status = 'stale' "
            "WHERE student_id = ? AND subject = ?",
            (student_id, subject),
        )
        connection.commit()
        # The snapshot cache is process-local and student keyed. Invalidate it
        # only after the attempt, responses, and diagnostic record commit.
        from database.learning_data import clear_learning_data_snapshot_cache

        clear_learning_data_snapshot_cache()
        return attempt_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@measure_function("database.get_recent_quiz_attempts")
def get_recent_quiz_attempts(student_id: int, limit: int = 5) -> list[DatabaseRowLike]:
    """Return recent quiz attempts belonging only to the requested student."""
    safe_limit = max(1, min(int(limit), 50))
    connection = get_connection()
    try:
        return connection.execute(
            """
            SELECT id, subject, topic, difficulty, total_questions,
                   correct_answers, score, completed_at
            FROM quiz_attempts
            WHERE student_id = ?
            ORDER BY completed_at DESC, id DESC
            LIMIT ?
            """,
            (student_id, safe_limit),
        ).fetchall()
    finally:
        connection.close()


@measure_function("database.get_subject_quiz_stats")
def get_subject_quiz_stats(student_id: int) -> list[DatabaseRowLike]:
    """Return actual attempt counts and average scores by subject for one student."""
    connection = get_connection()
    try:
        return connection.execute(
            """
            SELECT subject, COUNT(*) AS attempts, AVG(score) AS average_score,
                   SUM(correct_answers) AS correct_answers,
                   SUM(total_questions) AS total_questions
            FROM quiz_attempts
            WHERE student_id = ?
            GROUP BY subject
            ORDER BY subject
            """,
            (student_id,),
        ).fetchall()
    finally:
        connection.close()
