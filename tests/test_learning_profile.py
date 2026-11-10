"""Student-scoped quiz response persistence and learning profile tests."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import db as database
from database.learning_data import get_learning_data_snapshot
from modules.learning_profile import (
    MIN_CONCEPT_QUESTIONS,
    get_student_learning_profile,
)
from modules.quiz_engine import submit_quiz


def question(concept: str = "Array traversal") -> dict[str, object]:
    return {
        "question": "Which option follows the stated rule for this example?",
        "concept": concept,
        "topic": "Arrays and strings",
        "subject": "DSA",
        "options": ["A", "B", "C", "D"],
        "correct_option_index": 1,
        "correct_answer": "B",
        "explanation": "Option B is correct because it follows the rule in this example.",
    }


def quiz_state(student_id: int, key: str, answers: list[int | None], concept: str = "Array traversal"):
    questions = [question(concept) for _ in answers]
    return {
        "student_id": student_id,
        "subject": "DSA",
        "topic": "Arrays and strings",
        "difficulty": "Beginner",
        "attempt_key": key,
        "questions": questions,
        "answers": answers,
        "submitted": False,
    }


class LearningProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "learning.db"
        self.db_patch = patch.object(database, "DATABASE_PATH", self.db_path)
        self.db_patch.start()
        database.initialize_database()
        connection = database.get_connection()
        try:
            connection.executemany(
                "INSERT INTO students (display_name, email, password_hash) VALUES (?, ?, ?)",
                [("Student One", "one@example.test", "hash"), ("Student Two", "two@example.test", "hash")],
            )
            connection.commit()
        finally:
            connection.close()

    def tearDown(self):
        database._initialized_paths.discard(str(self.db_path.resolve()))
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_submission_persists_every_response_and_keeps_score_compatibility(self):
        state = quiz_state(1, "answers-1", [1, 0, None])
        result = submit_quiz(1, state)
        self.assertEqual((result["correct_answers"], result["incorrect_answers"], result["unanswered_questions"]), (1, 1, 1))
        self.assertEqual(state["attempt_id"], 1)

        connection = database.get_connection()
        try:
            rows = connection.execute(
                "SELECT student_id, attempt_id, question_id, subject, topic, concept, "
                "selected_answer, correct_answer, is_correct, answered_at "
                "FROM quiz_responses WHERE student_id = ? ORDER BY question_id",
                (1,),
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["question_id"], "q0001")
        self.assertEqual(rows[0]["attempt_id"], state["attempt_id"])
        self.assertEqual(rows[0]["subject"], "DSA")
        self.assertEqual(rows[0]["concept"], "Array traversal")
        self.assertEqual(rows[0]["selected_answer"], "B")
        self.assertEqual(rows[0]["correct_answer"], "B")
        self.assertEqual(rows[0]["is_correct"], 1)
        self.assertTrue(rows[0]["answered_at"])
        self.assertIsNone(rows[2]["selected_answer"])
        self.assertIsNone(rows[2]["is_correct"])
        self.assertEqual(len(database.get_recent_quiz_attempts(1)), 1)
        self.assertEqual(database.get_recent_quiz_attempts(1)[0]["score"], 33.33)

    def test_concept_accuracy_counts_correct_and_incorrect_answered_responses(self):
        submit_quiz(1, quiz_state(1, "accuracy-1", [1, 0, 1, 0], "Stacks"))
        profile = get_student_learning_profile(1)
        concept = profile["subjects"][0]["concept_performance"][0]
        self.assertEqual(concept["questions_attempted"], 4)
        self.assertEqual(concept["correct_answers"], 2)
        self.assertEqual(concept["incorrect_answers"], 2)
        self.assertEqual(concept["accuracy"], 50.0)
        self.assertEqual(concept["assessment"], "insufficiently_assessed")

    def test_minimum_sample_threshold_and_strong_weak_classification(self):
        for index in range(MIN_CONCEPT_QUESTIONS - 1):
            submit_quiz(1, quiz_state(1, f"small-{index}", [1], "Small sample concept"))
        profile = get_student_learning_profile(1)
        item = profile["subjects"][0]["concept_performance"][0]
        self.assertEqual(item["questions_attempted"], MIN_CONCEPT_QUESTIONS - 1)
        self.assertEqual(item["assessment"], "insufficiently_assessed")

        submit_quiz(1, quiz_state(1, "small-enough", [1], "Small sample concept"))
        submit_quiz(1, quiz_state(1, "strong-concept", [1] * 5, "Strong concept"))
        submit_quiz(1, quiz_state(1, "weak-concept", [0] * 5, "Weak concept"))
        profile = get_student_learning_profile(1)
        subject = profile["subjects"][0]
        self.assertIn("Strong concept", subject["strong_concepts"])
        self.assertIn("Weak concept", subject["weak_concepts"])
        self.assertNotIn("Small sample concept", subject["insufficiently_assessed_concepts"])

    def test_subject_summary_and_recent_performance_trend(self):
        for index in range(10):
            score = 20.0 if index < 5 else 80.0
            correct = int(score / 20)
            database.save_quiz_attempt(
                1, "DSA", "Arrays and strings", "Beginner", 5, correct,
                score, f"trend-{index}",
            )
        profile = get_student_learning_profile(1)
        self.assertEqual(profile["total_questions_attempted"], 50)
        subject = profile["subjects"][0]
        self.assertEqual(subject["quiz_count"], 10)
        self.assertEqual(subject["overall_accuracy"], 50.0)
        self.assertEqual(subject["recent_performance_trend"]["direction"], "improving")
        self.assertEqual(subject["recent_performance_trend"]["change_percentage_points"], 60.0)

    def test_recent_concept_performance_uses_latest_five_answered_responses(self):
        submit_quiz(1, quiz_state(1, "concept-recent-1", [1, 1, 1, 1, 1, 0], "Recency"))
        profile = get_student_learning_profile(1)
        item = profile["subjects"][0]["concept_performance"][0]
        self.assertEqual(item["questions_attempted"], 6)
        self.assertEqual(item["recent_questions_attempted"], 5)
        self.assertEqual(item["recent_accuracy"], 80.0)

    def test_empty_history_and_student_isolation(self):
        self.assertEqual(get_student_learning_profile(2), {
            "total_questions_attempted": 0,
            "overall_accuracy": None,
            "concepts_assessed": 0,
            "subjects": [],
        })
        submit_quiz(1, quiz_state(1, "private-1", [1], "Private concept"))
        self.assertEqual(get_student_learning_profile(2)["subjects"], [])
        snapshot = get_learning_data_snapshot(2)
        self.assertEqual(snapshot, {
            "subjects": [], "concepts": [], "topics": [],
            "response_metadata": [], "recent_attempts": [],
        })

    def test_learning_snapshot_cache_refreshes_after_submission_and_is_student_scoped(self):
        self.assertEqual(get_learning_data_snapshot(1)["subjects"], [])
        self.assertEqual(get_learning_data_snapshot(2)["subjects"], [])

        submit_quiz(1, quiz_state(1, "cache-refresh", [1]))

        refreshed = get_learning_data_snapshot(1)
        other_student = get_learning_data_snapshot(2)
        self.assertEqual(refreshed["subjects"][0]["quiz_count"], 1)
        self.assertEqual(other_student["subjects"], [])

    def test_valid_concept_and_topic_remain_separate(self):
        submit_quiz(1, quiz_state(1, "separate-valid", [1], "Queue operations"))
        profile = get_student_learning_profile(1)["subjects"][0]
        self.assertEqual([item["concept"] for item in profile["concept_performance"]], ["Queue operations"])
        self.assertEqual([item["topic"] for item in profile["topic_performance"]], ["Arrays and strings"])
        self.assertEqual(profile["concept_metadata_status"], "available")
        self.assertEqual(profile["responses_without_concept_metadata"], 0)

    def test_missing_concept_is_unavailable_not_assigned_to_valid_topic(self):
        state = quiz_state(1, "missing-concept", [1])
        state["questions"][0].pop("concept")
        submit_quiz(1, state)
        profile = get_student_learning_profile(1)["subjects"][0]
        self.assertEqual(profile["concept_performance"], [])
        self.assertEqual(profile["concepts_assessed"], 0)
        self.assertEqual(profile["concept_metadata_status"], "unavailable")
        self.assertEqual(profile["responses_without_concept_metadata"], 1)
        self.assertEqual(profile["topic_performance"][0]["topic"], "Arrays and strings")
        self.assertEqual(profile["topic_performance"][0]["questions_attempted"], 1)

    def test_mixed_concept_and_topic_only_responses_are_separate(self):
        state = quiz_state(1, "mixed-metadata", [1, 0])
        state["questions"][0]["concept"] = "Array traversal"
        state["questions"][1].pop("concept")
        submit_quiz(1, state)
        profile = get_student_learning_profile(1)["subjects"][0]
        self.assertEqual([item["concept"] for item in profile["concept_performance"]], ["Array traversal"])
        self.assertEqual(profile["concept_performance"][0]["questions_attempted"], 1)
        self.assertEqual(profile["topic_performance"][0]["questions_attempted"], 2)
        self.assertEqual(profile["concept_metadata_status"], "partial")
        self.assertEqual(profile["responses_without_concept_metadata"], 1)

    def test_concept_and_topic_profile_data_are_student_isolated(self):
        first_state = quiz_state(1, "isolation-concept-one", [1])
        first_state["questions"][0]["concept"] = "Student One concept"
        submit_quiz(1, first_state)
        second_state = quiz_state(2, "isolation-concept-two", [0])
        second_state["questions"][0]["concept"] = "Student Two concept"
        submit_quiz(2, second_state)
        first_profile = get_student_learning_profile(1)["subjects"][0]
        second_profile = get_student_learning_profile(2)["subjects"][0]
        self.assertEqual([item["concept"] for item in first_profile["concept_performance"]], ["Student One concept"])
        self.assertEqual([item["concept"] for item in second_profile["concept_performance"]], ["Student Two concept"])

    def test_historical_attempt_without_concept_metadata_is_not_backfilled(self):
        database.save_quiz_attempt(1, "Python", "Functions", "Intermediate", 4, 3, 75.0, "historical")
        profile = get_student_learning_profile(1)
        self.assertEqual(profile["subjects"][0]["overall_accuracy"], 75.0)
        self.assertEqual(profile["subjects"][0]["concepts_assessed"], 0)
        self.assertEqual(profile["subjects"][0]["concept_performance"], [])
        connection = database.get_connection()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM quiz_responses").fetchone()[0], 0)
        finally:
            connection.close()

    def test_versioned_migration_preserves_legacy_students_and_attempts(self):
        legacy_path = self.db_path.parent / "legacy-learning.db"
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute(
                "CREATE TABLE students (id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, email TEXT, "
                "password_hash TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute("INSERT INTO students (id, display_name) VALUES (7, 'Preserved Student')")
            connection.execute(
                "CREATE TABLE quiz_attempts (id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, "
                "subject TEXT NOT NULL, topic TEXT NOT NULL, score REAL NOT NULL, "
                "completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "INSERT INTO quiz_attempts (id, student_id, subject, topic, score) "
                "VALUES (11, 7, 'DBMS', 'Joins', 75)"
            )
            connection.commit()
        finally:
            connection.close()

        legacy_key = str(legacy_path.resolve())
        database._initialized_paths.discard(legacy_key)
        with patch.object(database, "DATABASE_PATH", legacy_path):
            database.initialize_database()
            database.initialize_database()
            database._initialize_database_schema()
            connection = database.get_connection()
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM students WHERE id = 7").fetchone()[0], 1)
                attempt = connection.execute(
                    "SELECT id, score, total_questions FROM quiz_attempts WHERE id = 11"
                ).fetchone()
                self.assertEqual((attempt["id"], attempt["score"], attempt["total_questions"]), (11, 75, 0))
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM quiz_responses").fetchone()[0], 0)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                connection.close()
        database._initialized_paths.discard(legacy_key)


if __name__ == "__main__":
    unittest.main()
