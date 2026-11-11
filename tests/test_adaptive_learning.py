"""Mocked Phase 5.3 diagnostic and adaptive learning behavior tests."""

import json
import sqlite3
import sys
import tempfile
import types
import unittest
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from streamlit.testing.v1 import AppTest

from database import db as database
from database.learning_data import (
    get_current_adaptive_recommendation,
    get_latest_diagnostic_assessment,
)
from modules.ai_tutor import TutorServiceError
from modules import adaptive_learning, adaptive_provider
from modules.quiz_engine import SUBJECT_TOPICS, submit_quiz
from ui.styles import GLOBAL_CSS


def diagnostic_question(index: int, *, topic: str | None = None, difficulty: str | None = None, concept: str | None = None):
    question_patterns = [
        f"Which result follows for Alpha traversal case {index}?",
        f"How does Beta lookup case {index} behave?",
        f"Why does Gamma structure case {index} remain valid?",
        f"Given Delta sequence case {index}, which result applies?",
        f"What is the time complexity of Epsilon operation case {index}?",
        f"Read Zeta code case {index}. What output follows?",
    ]
    return {
        "question": question_patterns[index % len(question_patterns)],
        "concept": concept if concept is not None else f"Distinct concept group {index}",
        "options": ["Option A", "Option B", "Option C", "Option D"],
        "correct_option_index": 1,
        "explanation": "Option B is correct because the stated rule selects this result.",
        "subject": "DSA",
        "topic": topic or SUBJECT_TOPICS["DSA"][index % len(SUBJECT_TOPICS["DSA"])],
        "difficulty": difficulty or ("Beginner", "Intermediate", "Advanced")[index % 3],
    }


def question_set(count: int = 10):
    return [diagnostic_question(index) for index in range(count)]


def quiz_state(student_id: int, attempt_key: str, questions, answers, *, difficulty="Beginner", topic="Arrays and strings"):
    return {
        "student_id": student_id,
        "subject": "DSA",
        "topic": topic,
        "difficulty": difficulty,
        "questions": questions,
        "answers": answers,
        "attempt_key": attempt_key,
        "submitted": False,
    }


class AdaptiveLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "adaptive.db"
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

    def test_diagnostic_generation_uses_metadata_mixed_difficulty_and_shared_adapter(self):
        payload = {"questions": question_set()}
        with patch(
            "modules.adaptive_learning.generate_adaptive_content_with_metadata",
            return_value=(json.dumps(payload), {
                "provider": "gemini", "task": "diagnostic", "fallback_used": False,
                "input_tokens": 200, "output_tokens": 1200,
            }),
        ) as provider:
            questions, metadata = adaptive_learning.generate_diagnostic_questions(
                1, "DSA", "Intermediate", with_metadata=True
            )
        self.assertEqual(len(questions), 10)
        self.assertEqual({item["difficulty"] for item in questions}, {"Beginner", "Intermediate", "Advanced"})
        self.assertTrue(all(item["topic"] in SUBJECT_TOPICS["DSA"] for item in questions))
        self.assertEqual(metadata["input_tokens"], 200)
        self.assertEqual(provider.call_args.kwargs["task"], "diagnostic")
        self.assertEqual(provider.call_args.kwargs["student_scope"], 1)
        self.assertEqual(provider.call_args.kwargs["output_token_limit"], adaptive_learning.DIAGNOSTIC_OUTPUT_TOKEN_LIMIT)

    def test_diagnostic_accepts_a_valid_json_code_fence_without_relaxing_validation(self):
        response = "```json\n" + json.dumps({"questions": question_set()}) + "\n```"
        with patch(
            "modules.adaptive_learning.generate_adaptive_content_with_metadata",
            return_value=(response, {"provider": "gemini"}),
        ):
            questions = adaptive_learning.generate_diagnostic_questions(1, "DSA", "Not sure")
        self.assertEqual(len(questions), 10)

    def test_valid_mocked_groq_structured_diagnostic_parses_and_tracks_tokens(self):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"questions": question_set()})))],
            usage=SimpleNamespace(prompt_tokens=321, completion_tokens=2100),
        )
        groq_module = types.ModuleType("groq")
        groq_module.Groq = Mock(return_value=client)
        groq_module.APIError = Exception
        groq_module.APIStatusError = type("APIStatusError", (Exception,), {})
        groq_module.APIConnectionError = type("APIConnectionError", (Exception,), {})
        with patch.dict(sys.modules, {"groq": groq_module}), \
             patch("modules.adaptive_provider.load_configuration"), \
             patch("modules.adaptive_provider.groq_api_usage_allowed", return_value=True), \
             patch("modules.adaptive_provider.get_groq_api_key", return_value="synthetic-key"), \
             patch("modules.adaptive_provider.get_groq_model", return_value="openai/gpt-oss-120b"):
            questions, metadata = adaptive_learning.generate_diagnostic_questions(
                1, "DSA", "Not sure", with_metadata=True,
            )
        self.assertEqual(len(questions), 10)
        self.assertEqual(metadata["provider"], "groq")
        self.assertEqual(metadata["input_tokens"], 321)
        self.assertEqual(metadata["output_tokens"], 2100)
        request = client.chat.completions.create.call_args.kwargs
        schema = request["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"]["questions"]["items"]["type"], "object")
        self.assertEqual(request["reasoning_effort"], "medium")
        self.assertEqual(request["max_completion_tokens"], adaptive_learning.DIAGNOSTIC_OUTPUT_TOKEN_LIMIT)

    def test_malformed_diagnostic_json_is_a_safe_validation_error(self):
        with patch(
            "modules.adaptive_learning.generate_adaptive_content_with_metadata",
            return_value=("```json\n{not valid}\n```", {"provider": "gemini"}),
        ):
            with self.assertRaisesRegex(adaptive_learning.QuizGenerationError, "invalid JSON"):
                adaptive_learning.generate_diagnostic_questions(1, "DSA", "Not sure")

    def test_diagnostic_submission_scores_deterministically_and_persists_separate_proficiency(self):
        state = quiz_state(1, "diagnostic-complete", question_set(), [1] * 10, topic="Initial diagnostic", difficulty="Mixed")
        state["self_assessed_proficiency"] = "Beginner"
        state["provider_metadata"] = {
            "provider": "groq", "fallback_used": False,
            "input_tokens": 300, "output_tokens": 900,
        }
        result = adaptive_learning.submit_diagnostic(1, state)
        self.assertEqual(result["self_assessed_proficiency"], "Beginner")
        self.assertEqual(result["demonstrated_proficiency"], "Advanced")
        self.assertEqual(result["accuracy"], 100.0)
        self.assertEqual(result["assessment_status"], "assessed")
        self.assertTrue(state["submitted"])
        latest = get_latest_diagnostic_assessment(1, "DSA")
        self.assertEqual(latest["provider"], "groq")
        self.assertEqual(latest["task"], "diagnostic")
        self.assertEqual(latest["input_tokens"], 300)
        self.assertEqual(latest["output_tokens"], 900)
        connection = database.get_connection()
        try:
            rows = connection.execute(
                "SELECT student_id, subject, topic, difficulty, concept FROM quiz_responses "
                "WHERE student_id = ? ORDER BY id", (1,),
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0]["topic"], question_set()[0]["topic"])
        self.assertEqual(rows[0]["difficulty"], "Beginner")
        self.assertIsNotNone(rows[0]["concept"])

    def test_small_diagnostic_sample_reports_insufficient_evidence(self):
        state = quiz_state(1, "diagnostic-small", question_set(), [1] * 7 + [None] * 3, topic="Initial diagnostic", difficulty="Mixed")
        state["self_assessed_proficiency"] = "Advanced"
        result = adaptive_learning.submit_diagnostic(1, state)
        self.assertEqual(result["demonstrated_proficiency"], "Insufficient evidence")
        self.assertEqual(result["assessment_status"], "insufficient_evidence")
        self.assertEqual(result["answered_questions"], 7)
        self.assertEqual(result["accuracy"], 100.0)

    def test_eight_diagnostic_answers_in_one_topic_are_insufficient(self):
        questions = [diagnostic_question(i, topic="Arrays and strings") for i in range(10)]
        state = quiz_state(1, "diagnostic-narrow-topic", questions, [1] * 8 + [None] * 2)
        state["self_assessed_proficiency"] = "Advanced"
        result = adaptive_learning.submit_diagnostic(1, state)
        self.assertEqual(result["demonstrated_proficiency"], "Insufficient evidence")
        self.assertEqual(result["assessment_status"], "insufficient_evidence")
        self.assertFalse(result["topic_coverage_met"])
        self.assertIn("Topic coverage is inadequate", result["assessment_note"])

    def test_diagnostic_requires_all_topics_when_subject_has_fewer_than_three(self):
        two_topic_subjects = {"Tiny subject": ["Topic A", "Topic B"]}
        with patch("modules.adaptive_learning.SUBJECT_TOPICS", two_topic_subjects):
            questions = [
                diagnostic_question(i, topic="Topic A" if i < 8 else "Topic B")
                for i in range(10)
            ]
            state = quiz_state(1, "diagnostic-small-subject", questions, [1] * 10)
            state["subject"] = "Tiny subject"
            state["self_assessed_proficiency"] = "Beginner"
            result = adaptive_learning.submit_diagnostic(1, state)
            self.assertEqual(result["required_topics"], 2)
            self.assertTrue(result["topic_coverage_met"])
            self.assertEqual(result["demonstrated_proficiency"], "Advanced")

    def test_diagnostic_coverage_across_three_topics_supports_estimate(self):
        topics = SUBJECT_TOPICS["DSA"][:3]
        questions = [diagnostic_question(i, topic=topics[i % 3]) for i in range(10)]
        state = quiz_state(1, "diagnostic-covered", questions, [1] * 10)
        state["self_assessed_proficiency"] = "Beginner"
        result = adaptive_learning.submit_diagnostic(1, state)
        self.assertEqual(result["assessed_topics"], 3)
        self.assertTrue(result["topic_coverage_met"])
        self.assertEqual(result["demonstrated_proficiency"], "Advanced")

    def test_adaptive_difficulty_increases_and_decreases_with_recent_topic_results(self):
        strong_questions = [diagnostic_question(index, topic="Arrays and strings", difficulty="Beginner", concept="Array traversal") for index in range(5)]
        submit_quiz(1, quiz_state(1, "difficulty-strong", strong_questions, [1] * 5, difficulty="Beginner"))
        self.assertEqual(adaptive_learning.recommended_difficulty(1, "DSA", "Arrays and strings"), "Intermediate")

        weak_questions = [diagnostic_question(index, topic="Linked lists", difficulty="Advanced", concept="List insertion") for index in range(3)]
        submit_quiz(1, quiz_state(1, "difficulty-weak", weak_questions, [0] * 3, difficulty="Advanced", topic="Linked lists"))
        self.assertEqual(adaptive_learning.recommended_difficulty(1, "DSA", "Linked lists"), "Intermediate")

    def test_difficulty_uses_selected_concept_without_mixing_other_concepts(self):
        high_questions = [diagnostic_question(i, topic="Arrays and strings", concept="High concept") for i in range(5)]
        submit_quiz(1, quiz_state(1, "concept-high", high_questions, [1] * 5, difficulty="Advanced"))
        low_questions = [diagnostic_question(i, topic="Arrays and strings", concept="Low concept") for i in range(3)]
        submit_quiz(1, quiz_state(1, "concept-low", low_questions, [0] * 3, difficulty="Advanced"))
        self.assertEqual(
            adaptive_learning.recommended_difficulty(1, "DSA", "Arrays and strings", concept="Low concept"),
            "Intermediate",
        )

    def test_topic_difficulty_fallback_when_concept_metadata_is_missing(self):
        questions = [diagnostic_question(i, topic="Arrays and strings", concept="") for i in range(5)]
        submit_quiz(1, quiz_state(1, "topic-fallback", questions, [1] * 5, difficulty="Beginner"))
        self.assertEqual(adaptive_learning.recommended_difficulty(1, "DSA", "Arrays and strings"), "Intermediate")

    def test_recommendation_is_structured_cached_and_invalidated_by_new_attempt(self):
        database.save_quiz_attempt(1, "DSA", "Initial diagnostic", "Mixed", 10, 6, 60.0, "rec-seed")
        payload = {
            "next_topic": "Arrays and strings",
            "reason": "Recent measured accuracy shows this topic could use focused practice.",
            "priority": "high",
            "study_activity": "Work through three short array traversal exercises.",
            "recommended_difficulty": "Beginner",
            "learning_objective": "Trace a traversal and predict its output.",
        }
        with patch(
            "modules.adaptive_learning.generate_adaptive_content_with_metadata",
            return_value=(json.dumps(payload), {
                "provider": "groq", "fallback_used": False,
                "input_tokens": 200, "output_tokens": 150,
            }),
        ) as provider:
            first = adaptive_learning.get_learning_recommendation(1, "DSA")
            second = adaptive_learning.get_learning_recommendation(1, "DSA")
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(first["recommendation"]["recommended_difficulty"], "Beginner")
        self.assertEqual(first["task"], "recommendation")
        self.assertIsNotNone(get_current_adaptive_recommendation(1, "DSA"))

        database.save_quiz_attempt(1, "DSA", "Arrays and strings", "Beginner", 5, 2, 40.0, "rec-new-performance")
        self.assertIsNone(get_current_adaptive_recommendation(1, "DSA"))
        with patch(
            "modules.adaptive_learning.generate_adaptive_content_with_metadata",
            return_value=(json.dumps(payload), {"provider": "gemini", "fallback_used": True}),
        ) as refresh_provider:
            refreshed = adaptive_learning.get_learning_recommendation(1, "DSA")
        self.assertFalse(refreshed["cached"])
        refresh_provider.assert_called_once()

    def test_recommendations_are_student_specific_and_topics_are_allowlisted(self):
        database.save_quiz_attempt(1, "DSA", "Arrays and strings", "Beginner", 5, 2, 40.0, "student-one-seed")
        payload = {
            "next_topic": "Invented syllabus topic",
            "reason": "Recent measured accuracy shows this topic could use focused practice.",
            "priority": "high",
            "study_activity": "Work through three short exercises.",
            "recommended_difficulty": "Beginner",
            "learning_objective": "Trace an algorithm and predict its output.",
        }
        with patch(
            "modules.adaptive_learning.generate_adaptive_content_with_metadata",
            return_value=(json.dumps(payload), {"provider": "gemini", "fallback_used": False}),
        ):
            with self.assertRaisesRegex(adaptive_learning.AdaptiveLearningError, "unavailable topic"):
                adaptive_learning.get_learning_recommendation(1, "DSA")
        self.assertIsNone(get_current_adaptive_recommendation(2, "DSA"))
        with self.assertRaisesRegex(adaptive_learning.AdaptiveLearningError, "Complete a diagnostic"):
            adaptive_learning.get_learning_recommendation(2, "DSA")

    def test_version_one_database_upgrade_preserves_saved_responses(self):
        legacy_path = self.db_path.parent / "phase52.db"
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute("CREATE TABLE students (id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, email TEXT, password_hash TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("INSERT INTO students (id, display_name) VALUES (1, 'Preserved')")
            connection.execute("CREATE TABLE quiz_attempts (id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, subject TEXT NOT NULL, topic TEXT NOT NULL, score REAL NOT NULL, completed_at TEXT NOT NULL, difficulty TEXT NOT NULL, total_questions INTEGER NOT NULL, correct_answers INTEGER NOT NULL, attempt_key TEXT)")
            connection.execute("CREATE UNIQUE INDEX idx_quiz_attempt_id_student ON quiz_attempts(id, student_id)")
            connection.execute("INSERT INTO quiz_attempts VALUES (4, 1, 'DSA', 'Arrays and strings', 80, CURRENT_TIMESTAMP, 'Beginner', 5, 4, 'preserved')")
            connection.execute("CREATE TABLE quiz_responses (id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, attempt_id INTEGER NOT NULL, question_id TEXT NOT NULL, subject TEXT NOT NULL, topic TEXT NOT NULL, concept TEXT, selected_answer TEXT, correct_answer TEXT NOT NULL, is_correct INTEGER, answered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(attempt_id, question_id))")
            connection.execute("INSERT INTO quiz_responses (id, student_id, attempt_id, question_id, subject, topic, concept, selected_answer, correct_answer, is_correct) VALUES (9, 1, 4, 'q0001', 'DSA', 'Arrays and strings', 'Traversal', 'B', 'B', 1)")
            connection.execute("PRAGMA user_version = 1")
            connection.commit()
        finally:
            connection.close()

        with patch.object(database, "DATABASE_PATH", legacy_path):
            database._initialize_database_schema()
            connection = database.get_connection()
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT id, concept FROM quiz_responses WHERE id = 9").fetchone()["concept"], "Traversal")
                columns = {row["name"] for row in connection.execute("PRAGMA table_info(quiz_responses)")}
                self.assertIn("difficulty", columns)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM diagnostic_assessments").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM adaptive_recommendations").fetchone()[0], 0)
            finally:
                connection.close()

    def test_provider_metadata_reports_gemini_fallback_without_inventing_tokens(self):
        def fake_gemini(_prompt, _schema, *, feature, max_output_tokens, usage_out):
            self.assertEqual(feature, "adaptive")
            self.assertEqual(max_output_tokens, 321)
            usage_out.update({"input_tokens": 25, "output_tokens": 40})
            return '{"ok":true}'

        with patch("modules.adaptive_provider.load_configuration"), \
             patch("modules.adaptive_provider.groq_api_usage_allowed", return_value=True), \
             patch("modules.adaptive_provider.get_groq_api_key", return_value="synthetic"), \
             patch("modules.adaptive_provider._groq_request", side_effect=TutorServiceError("down", status_code=503)) as groq, \
             patch("modules.adaptive_provider.generate_structured_content", side_effect=fake_gemini):
            content, metadata = adaptive_provider.generate_adaptive_content_with_metadata(
                "prompt", {"type": "object"}, "recommendation", student_scope=1, output_token_limit=321,
            )
        self.assertEqual(content, '{"ok":true}')
        self.assertEqual(metadata, {
            "provider": "gemini", "task": "recommendation", "fallback_used": True,
            "input_tokens": 25, "output_tokens": 40,
        })
        self.assertEqual(groq.call_count, 1)

    def test_learning_path_page_renders_without_provider_call_on_page_load(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "5_Learning_Path.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 1, "display_name": "Student One", "email": "one@example.test",
        }
        with patch("modules.adaptive_learning.generate_adaptive_content_with_metadata") as provider:
            app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any(title.value == "Learning Path" for title in app.title))
        provider.assert_not_called()

    def test_learning_path_renders_compact_metrics_concept_counts_and_recommendation(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "5_Learning_Path.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 1, "display_name": "Student One", "email": "one@example.test",
        }
        diagnostic = {
            "self_assessed_proficiency": "Intermediate",
            "demonstrated_proficiency": "Beginner",
            "answered_questions": 8,
            "accuracy": 37.5,
            "assessment_status": "assessed",
        }
        recommendation = {
            "next_topic": "Arrays and strings",
            "reason": "Recent accuracy is 40%; strengthen traversal.",
            "priority": "high",
            "study_activity": "Trace three array examples.",
            "recommended_difficulty": "Beginner",
            "learning_objective": "Correctly trace 4 of 5 examples.",
        }
        subject_profile = {
            "subject": "DSA",
            "total_questions_attempted": 12,
            "overall_accuracy": 58.33,
            "recent_performance_trend": {"direction": "improving"},
            "strong_concepts": ["Queue operations", "Stack order"],
            "developing_concepts": ["Array traversal"],
            "weak_concepts": ["String matching"],
            "insufficiently_assessed_concepts": [
                "Array Indexing", "Array Memory Allocation", "Array Memory Layout",
                "Array Search Complexity", "Array Time Complexity", "Array index access",
                "Sliding Window Technique", "String Immutability", "Two-Pointer Strategy",
                "Two-Pointer Technique", "Exponential growth doubling input", "Dijkstra's algorithm",
                "Vertex degree", "Hash table search", "Singly linked list head insertion",
                "Quicksort worst case", "Array-based stack", "Queue via two stacks",
                "BST inorder traversal",
            ],
            "concept_metadata_status": "available",
            "topic_performance": [{
                "topic": "Arrays and strings", "correct_answers": 7,
                "incorrect_answers": 5, "recent_accuracy": 40.0,
                "recent_questions_attempted": 5,
            }],
        }
        row = {
            "payload_json": json.dumps(recommendation), "provider": "groq",
            "task": "recommendation", "fallback_used": False,
            "input_tokens": 120, "output_tokens": 80,
        }
        with patch("database.learning_data.get_latest_diagnostic_assessment", return_value=diagnostic), \
             patch("database.learning_data.get_current_adaptive_recommendation", return_value=row), \
             patch("modules.learning_profile.get_student_learning_profile", return_value={"subjects": [subject_profile]}), \
             patch("modules.adaptive_learning.generate_adaptive_content_with_metadata") as provider:
            app.run()
        self.assertFalse(app.exception)
        self.assertEqual({metric.label for metric in app.metric} & {
            "Self-assessed", "Demonstrated", "Questions answered", "Subject accuracy",
        }, {"Self-assessed", "Demonstrated", "Questions answered", "Subject accuracy"})
        self.assertEqual(
            {selectbox.key for selectbox in app.selectbox},
            {"learning_path_subject", "learning_self_assessed_1_DSA"},
        )
        rendered = "\n".join(element.value for element in app.markdown)
        for label in (
            "Queue operations", "Array traversal", "String matching", "1 concept",
            "19 concepts", "BST inorder traversal",
            "RECOMMENDED NEXT STEP", "Recent accuracy is", "Study activity",
            "Trace three array examples.", "Learning objective", "Correctly trace",
            "Start practice",
        ):
            self.assertIn(label, rendered + "\n" + "\n".join(button.label for button in app.button))
        insufficient_names = subject_profile["insufficiently_assessed_concepts"]
        self.assertEqual(len(insufficient_names), 19)
        rendered_concept_html = unescape(next(
            item.value for item in app.markdown if "lp-concept-card-insufficiently-assessed" in item.value
        ))
        self.assertEqual([rendered_concept_html.count(name) for name in insufficient_names], [1] * 19)
        self.assertEqual(
            [rendered_concept_html.index(name) for name in insufficient_names],
            sorted(rendered_concept_html.index(name) for name in insufficient_names),
        )
        self.assertTrue(any(button.label == "Start practice" for button in app.button))
        self.assertTrue(any(button.label == "Refresh path" for button in app.button))
        self.assertFalse(app.expander)
        self.assertIn("grid-template-columns:repeat(4,minmax(0,1fr))", GLOBAL_CSS)
        self.assertIn("grid-auto-rows:220px", GLOBAL_CSS)
        self.assertIn("box-sizing:border-box", GLOBAL_CSS)
        self.assertIn("height:220px; min-width:0; min-height:220px; max-height:220px", GLOBAL_CSS)
        self.assertIn("overflow:hidden", GLOBAL_CSS)
        self.assertIn("overflow-y:auto", GLOBAL_CSS)
        self.assertIn("overflow-x:hidden", GLOBAL_CSS)
        self.assertIn(".st-key-lp-concept-grid .al-concept-tags {", GLOBAL_CSS)
        self.assertIn("flex:0 0 auto", GLOBAL_CSS)
        self.assertIn("--lp-select-control-width:250px; --lp-select-control-height:2.5rem", GLOBAL_CSS)
        self.assertIn(".st-key-lp-subject-control [data-baseweb=\"select\"],", GLOBAL_CSS)
        self.assertIn(".st-key-lp-diagnostic-controls [data-baseweb=\"select\"]", GLOBAL_CSS)
        self.assertIn("justify-content:flex-end", GLOBAL_CSS)
        self.assertNotIn("Input tokens", rendered)
        self.assertNotIn("LOCAL API USAGE", rendered)
        provider.assert_not_called()

    def test_learning_path_empty_recommendation_keeps_generate_action_within_empty_state(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "5_Learning_Path.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 1, "display_name": "Student One", "email": "one@example.test",
        }
        with patch("database.learning_data.get_current_adaptive_recommendation", return_value=None), \
             patch("modules.learning_profile.get_student_learning_profile", return_value={"subjects": []}), \
             patch("modules.adaptive_learning.get_learning_recommendation") as generate:
            app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any(button.label == "Generate learning path" for button in app.button))
        self.assertTrue(any("Build enough evidence" in item.value for item in app.markdown))
        generate.assert_not_called()

    def test_learning_path_recommendation_wraps_long_content_without_narrowing(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "5_Learning_Path.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 1, "display_name": "Student One", "email": "one@example.test",
        }
        long_topic = "A deliberately long recommended topic name " * 5
        long_reason = "A detailed explanation that should use the card width and wrap naturally. " * 12
        recommendation = {
            "next_topic": long_topic,
            "reason": long_reason,
            "priority": "medium",
            "study_activity": "Compare worked examples and explain each step. " * 8,
            "recommended_difficulty": "Intermediate",
            "learning_objective": "Apply the concept to a new problem. " * 8,
        }
        row = {"payload_json": json.dumps(recommendation)}
        with patch("database.learning_data.get_latest_diagnostic_assessment", return_value=None), \
             patch("database.learning_data.get_current_adaptive_recommendation", return_value=row), \
             patch("modules.learning_profile.get_student_learning_profile", return_value={"subjects": []}), \
             patch("modules.adaptive_learning.get_learning_recommendation") as generate:
            app.run()
        self.assertFalse(app.exception)
        rendered = unescape("\n".join(element.value for element in app.markdown))
        self.assertIn(long_topic, rendered)
        self.assertIn(long_reason, rendered)
        self.assertIn("Compare worked examples", rendered)
        self.assertIn("Apply the concept", rendered)
        self.assertTrue(any(button.label == "Start practice" for button in app.button))
        self.assertTrue(any(button.label == "Refresh path" for button in app.button))
        self.assertIn(".lp-recommendation-explanation { box-sizing:border-box; width:100%; min-width:0", GLOBAL_CSS)
        self.assertIn(".lp-recommendation-reason { width:100%; max-width:none", GLOBAL_CSS)
        self.assertIn(".st-key-lp-recommendation-actions [data-testid=\"stHorizontalBlock\"] { display:flex!important", GLOBAL_CSS)
        self.assertIn("justify-content:flex-end", GLOBAL_CSS)
        generate.assert_not_called()

    def test_learning_path_all_empty_concept_categories_keep_empty_list_content(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "5_Learning_Path.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 1, "display_name": "Student One", "email": "one@example.test",
        }
        subject_profile = {
            "subject": "DSA",
            "total_questions_attempted": 0,
            "overall_accuracy": None,
            "recent_performance_trend": {"direction": "not_enough_data"},
            "strong_concepts": [],
            "developing_concepts": [],
            "weak_concepts": [],
            "insufficiently_assessed_concepts": [],
            "concept_metadata_status": "available",
            "topic_performance": [],
        }
        with patch("modules.learning_profile.get_student_learning_profile", return_value={"subjects": [subject_profile]}), \
             patch("database.learning_data.get_latest_diagnostic_assessment", return_value=None), \
             patch("database.learning_data.get_current_adaptive_recommendation", return_value=None):
            app.run()
        self.assertFalse(app.exception)
        rendered = "\n".join(element.value for element in app.markdown)
        for empty_message in (
            "No concepts classified as strong yet.",
            "Not enough evidence to classify concepts yet.",
            "No concepts currently classified as weak.",
            "No concepts currently need further assessment.",
        ):
            self.assertIn(empty_message, rendered)
        self.assertFalse(app.expander)

    def test_learning_path_distinguishes_unavailable_profile_from_empty_categories(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "5_Learning_Path.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 1, "display_name": "Student One", "email": "one@example.test",
        }
        with patch(
            "modules.learning_profile.get_student_learning_profile",
            side_effect=sqlite3.OperationalError("profile storage unavailable"),
        ):
            app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Could not load your performance profile" in item.value for item in app.error))
        self.assertTrue(any("Concept results will appear here" in item.value for item in app.markdown))
        self.assertNotIn("No concepts classified as strong yet.", "\n".join(item.value for item in app.markdown))

    def test_learning_path_shows_safe_error_for_malformed_diagnostic_response(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "5_Learning_Path.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 1, "display_name": "Student One", "email": "one@example.test",
        }
        app.run()
        with patch(
            "modules.adaptive_learning.generate_adaptive_content_with_metadata",
            return_value=("not JSON", {"provider": "gemini"}),
        ):
            next(button for button in app.button if button.label == "Start diagnostic").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("invalid JSON" in error.value for error in app.error))

    def test_progress_page_handles_empty_one_attempt_and_calculated_trend(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "4_Progress.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 1, "display_name": "Student One", "email": "one@example.test",
        }
        with patch(
            "database.db.get_recent_quiz_attempts",
            side_effect=AssertionError("Progress should reuse the learning snapshot."),
        ):
            app.run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.selectbox), 1)
        self.assertEqual(app.selectbox[0].label, "Explore Subject")
        self.assertTrue(app.selectbox[0].disabled)
        self.assertTrue(any(button.key == "progress-concept-tile-button" for button in app.button))
        self.assertTrue(any(button.key == "progress-trends-tile-button" for button in app.button))
        tile_markup = "\n".join(item.value for item in app.markdown)
        self.assertIn("No concepts classified yet", tile_markup)
        self.assertIn("Not enough history yet", tile_markup)
        self.assertIn("See how well you understand individual concepts.", tile_markup)
        self.assertIn("Compare your recent performance with earlier attempts.", tile_markup)
        self.assertTrue(any("Complete a quiz to build" in item.value for item in app.caption))

        database.save_quiz_attempt(1, "DSA", "Arrays and strings", "Beginner", 5, 3, 60.0, "progress-one")
        app.run()
        self.assertFalse(app.exception)
        tile_markup = "\n".join(item.value for item in app.markdown)
        self.assertIn("Not enough history yet", tile_markup)
        self.assertIn("Insufficient history", tile_markup)

        for index, score in enumerate((30, 40, 50, 60, 70), start=2):
            database.save_quiz_attempt(
                1, "DSA", "Arrays and strings", "Intermediate", 10,
                score // 10, float(score), f"progress-{index}",
            )
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any(item.label == "Recent performance" for item in app.metric))
        self.assertTrue(any("Arrays and strings" in item.value for item in app.markdown))

        responses = [
            {"question_id": f"tile-strong-{index}", "concept": "Array traversal", "selected_answer": "A",
             "correct_answer": "A", "is_correct": index < 4}
            for index in range(5)
        ] + [
            {"question_id": f"tile-weak-{index}", "concept": "Linked list insertion", "selected_answer": "B",
             "correct_answer": "A", "is_correct": index == 0}
            for index in range(5)
        ]
        database.save_quiz_attempt(1, "DSA", "Arrays", "Intermediate", 10, 5, 50.0, "progress-concepts", responses=responses)
        app.run()
        tile_markup = "\n".join(item.value for item in app.markdown)
        self.assertIn("</strong> concepts tracked", tile_markup)
        self.assertIn("1 strong", tile_markup)
        self.assertIn("1 weak", tile_markup)
        self.assertIn("Improving", tile_markup)
        self.assertIn("percentage points", tile_markup)

    def test_progress_subject_selection_updates_metrics_and_tiles_navigate(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "4_Progress.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 1, "display_name": "Student One", "email": "one@example.test",
        }
        database.save_quiz_attempt(1, "DSA", "Arrays", "Beginner", 5, 2, 40.0, "overview-dsa")
        database.save_quiz_attempt(1, "Python", "Functions", "Intermediate", 5, 4, 80.0, "overview-python")
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(next(item.value for item in app.metric if item.label == "Subject accuracy"), "40.0%")

        app.selectbox(key="progress_subject").select("Python").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["progress_subject"], "Python")
        self.assertEqual(next(item.value for item in app.metric if item.label == "Subject accuracy"), "80.0%")
        self.assertTrue(any("Functions" in item.value for item in app.markdown))

        with patch("streamlit.switch_page") as switch_page:
            app.button(key="progress-concept-tile-button").click().run()
            switch_page.assert_called_with("pages/6_Concept_Performance.py")
            app.button(key="progress-trends-tile-button").click().run()
            switch_page.assert_called_with("pages/7_Recent_Trends.py")
        self.assertEqual(app.session_state["progress_subject"], "Python")

    def test_concept_performance_detail_is_student_scoped(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "6_Concept_Performance.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 1, "display_name": "Student One", "email": "one@example.test",
        }
        responses = [
            {"question_id": f"strong-{index}", "concept": "Array traversal", "selected_answer": "A",
             "correct_answer": "A", "is_correct": index < 4}
            for index in range(5)
        ] + [
            {"question_id": f"weak-{index}", "concept": "Linked list insertion", "selected_answer": "B",
             "correct_answer": "A", "is_correct": index == 0}
            for index in range(5)
        ]
        database.save_quiz_attempt(1, "DSA", "Arrays", "Beginner", 10, 5, 50.0, "concepts-one", responses=responses)
        database.save_quiz_attempt(
            2, "DSA", "Arrays", "Beginner", 1, 1, 100.0, "concepts-two",
            responses=[{"question_id": "private", "concept": "Private student two concept",
                        "selected_answer": "A", "correct_answer": "A", "is_correct": True}],
        )

        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(next(item.value for item in app.metric if item.label == "Strong"), "1")
        self.assertEqual(next(item.value for item in app.metric if item.label == "Weak"), "1")
        rendered = "\n".join(item.value for item in app.markdown)
        self.assertIn("Array traversal", rendered)
        self.assertIn("Linked list insertion", rendered)
        self.assertNotIn("Private student two concept", rendered)

    def test_recent_trends_detail_uses_scoped_history_and_insufficient_state(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "7_Recent_Trends.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 1, "display_name": "Student One", "email": "one@example.test",
        }
        database.save_quiz_attempt(1, "DSA", "Arrays", "Beginner", 5, 2, 40.0, "trend-1")
        app.run(timeout=15)
        self.assertFalse(app.exception)
        self.assertTrue(any("Not enough quiz history yet" in item.value for item in app.markdown))
        self.assertEqual(next(item.value for item in app.metric if item.label == "Direction"), "Insufficient History")

        for index, score in enumerate((50, 60, 70, 80, 90), start=2):
            database.save_quiz_attempt(
                1, "DSA", "Arrays", "Intermediate", 10, score // 10,
                float(score), f"trend-{index}",
            )
        database.save_quiz_attempt(2, "DSA", "Student Two private topic", "Beginner", 5, 5, 100.0, "trend-two")
        app.run(timeout=15)
        self.assertFalse(app.exception)
        self.assertEqual(next(item.value for item in app.metric if item.label == "Direction"), "Improving")
        self.assertTrue(any("Saved quiz scores" in item.value for item in app.markdown))
        self.assertFalse(any("Student Two private topic" in item.value for item in app.markdown))
        chart = app.get("vega_lite_chart")[0]
        chart_spec = json.loads(chart.proto.spec)
        self.assertEqual([layer["mark"]["type"] for layer in chart_spec["layer"]], ["line", "point", "point"])
        self.assertEqual(chart_spec["layer"][0]["mark"]["color"], "#92400E")
        self.assertEqual(chart_spec["layer"][2]["mark"]["color"], "#92400E")
        self.assertEqual(chart_spec["config"]["axis"]["labelColor"], "#444444")
        self.assertEqual(chart_spec["config"]["axis"]["gridColor"], "#E5E5E5")
        self.assertEqual(
            {parameter["name"] for parameter in chart_spec["params"]},
            {"recent_score_hover", "recent_score_zoom"},
        )

    def test_progress_detail_tiles_share_responsive_equal_height_rules(self):
        styles = (Path(__file__).resolve().parent.parent / "ui" / "styles.py").read_text(encoding="utf-8")
        self.assertIn(".st-key-progress-detail-grid [data-testid=\"stHorizontalBlock\"] { align-items:stretch; }", styles)
        self.assertIn(".st-key-progress-concept-tile div.stButton > button,", styles)
        self.assertIn(".st-key-progress-trends-tile div.stButton > button", styles)
        self.assertIn(".al-progress-tile-content", styles)
        self.assertIn(".al-progress-tile-footer { margin-top:auto", styles)
        self.assertIn("overflow-wrap:anywhere", styles)
        self.assertIn("min-height:14rem", styles)
        self.assertIn(".st-key-progress-detail-grid [data-testid=\"stHorizontalBlock\"] { display:flex!important; flex-direction:column", styles)

    def test_recommendation_starts_practice_with_adaptive_selection(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "3_Practice.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 1, "display_name": "Student One", "email": "one@example.test",
        }
        app.session_state["adaptive_practice_selection"] = {
            "student_id": 1,
            "subject": "Python", "topic": "Functions", "difficulty": "Advanced",
        }
        app.run()
        self.assertFalse(app.exception)
        controls = {item.key: item.value for item in app.selectbox}
        self.assertEqual(controls["practice_subject"], "Python")
        self.assertEqual(controls["practice_topic"], "Functions")
        self.assertEqual(controls["practice_difficulty"], "Advanced")

    def test_practice_discards_handoff_owned_by_another_student(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "3_Practice.py"
        app = AppTest.from_file(page)
        app.session_state["student"] = {
            "id": 2, "display_name": "Student Two", "email": "two@example.test",
        }
        app.session_state["practice_owner_student_id"] = 2
        app.session_state["adaptive_practice_selection"] = {
            "student_id": 1,
            "subject": "Python", "topic": "Functions", "difficulty": "Advanced",
        }
        app.run()
        self.assertFalse(app.exception)
        controls = {item.key: item.value for item in app.selectbox}
        self.assertNotEqual(controls["practice_subject"], "Python")
        self.assertNotEqual(controls["practice_topic"], "Functions")
        self.assertNotEqual(controls["practice_difficulty"], "Advanced")
        self.assertNotIn("adaptive_practice_selection", app.session_state)


if __name__ == "__main__":
    unittest.main()
