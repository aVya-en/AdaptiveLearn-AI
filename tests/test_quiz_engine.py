"""Mocked quiz generation, evaluation, persistence, and isolation tests."""

import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from google.genai import types
from streamlit.testing.v1 import AppTest

import database.db as database
from modules import ai_tutor, quiz_engine


def make_question(index: int = 0, **overrides):
    stems = [
        "What property does test item {i} demonstrate?",
        "How should a student apply test item {i}?",
        "Given test item {i}, which outcome is expected?",
        "Why is test item {i} useful in this case?",
        "Which statement describes test item {i}?",
    ]
    question = {
        "question": stems[index % len(stems)].format(i=index),
        "concept": f"distinct test concept {index}",
        "options": ["Option A", "Option B", "Option C", "Option D"],
        "correct_option_index": 1,
        "explanation": "Option B is correct because this test fixture defines it as the answer.",
        "subject": "DSA",
        "topic": "Arrays and strings",
        "difficulty": "Beginner",
    }
    question.update(overrides)
    return question


def make_quiz_state(student_id: int, attempt_key: str = "stable-test-attempt"):
    questions = [make_question(index) for index in range(5)]
    return {
        "student_id": student_id,
        "subject": "DSA",
        "topic": "Arrays and strings",
        "difficulty": "Beginner",
        "questions": questions,
        "answers": [1, 0, None, 1, 2],
        "attempt_key": attempt_key,
        "submitted": False,
    }


class QuizGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        quiz_engine.clear_quiz_cache()

    def test_response_schema_constructs_without_integer_enum_validation_error(self) -> None:
        question_schema = quiz_engine.QUIZ_RESPONSE_SCHEMA["properties"]["questions"]["items"]
        correct_index_schema = question_schema["properties"]["correct_option_index"]
        self.assertEqual(correct_index_schema, {"type": "INTEGER"})

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=quiz_engine.QUIZ_RESPONSE_SCHEMA,
        )
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertIsNotNone(config.response_schema)

    def test_valid_structured_quiz_is_normalized(self) -> None:
        payload = {"questions": [make_question(index) for index in range(5)]}
        with patch("modules.quiz_engine.generate_structured_content", return_value=json.dumps(payload)) as generate:
            questions = quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        self.assertEqual(len(questions), 5)
        self.assertEqual(questions[0]["correct_answer"], "Option B")
        self.assertEqual(questions[0]["correct_option_index"], 1)
        schema = generate.call_args.args[1]
        self.assertEqual(schema["properties"]["questions"]["items"]["properties"]["options"]["type"], "ARRAY")

    def test_invalid_json_is_rejected_without_fallback_quiz(self) -> None:
        with patch("modules.quiz_engine.generate_structured_content", return_value="not json"):
            with self.assertRaisesRegex(quiz_engine.QuizGenerationError, "invalid JSON"):
                quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)

    def test_missing_fields_are_rejected(self) -> None:
        payload = {"questions": [make_question(index) for index in range(5)]}
        payload["questions"][0].pop("explanation")
        with self.assertRaisesRegex(quiz_engine.QuizGenerationError, "missing required fields"):
            quiz_engine.validate_quiz_payload(payload, "DSA", "Arrays and strings", "Beginner", 5)

    def test_empty_explanation_is_rejected(self) -> None:
        payload = {"questions": [make_question(index) for index in range(5)]}
        payload["questions"][0]["explanation"] = "   "
        with self.assertRaisesRegex(quiz_engine.QuizGenerationError, "missing or empty explanation"):
            quiz_engine.validate_quiz_payload(payload, "DSA", "Arrays and strings", "Beginner", 5)

    def test_exact_and_near_duplicate_questions_are_rejected(self) -> None:
        payload = {"questions": [make_question(index) for index in range(5)]}
        payload["questions"][1]["question"] = payload["questions"][0]["question"].replace("?", "!")
        with self.assertRaisesRegex(quiz_engine.QuizGenerationError, "duplicates another question"):
            quiz_engine.validate_quiz_payload(payload, "DSA", "Arrays and strings", "Beginner", 5)

        payload = {"questions": [make_question(index) for index in range(5)]}
        payload["questions"][1]["question"] = "What property does test item 0 demonstrate in practice?"
        with self.assertRaisesRegex(quiz_engine.QuizGenerationError, "too similar in wording"):
            quiz_engine.validate_quiz_payload(payload, "DSA", "Arrays and strings", "Beginner", 5)

    def test_repeated_concept_is_rejected_but_shared_technical_vocabulary_is_allowed(self) -> None:
        payload = {"questions": [make_question(index) for index in range(5)]}
        payload["questions"][1]["concept"] = payload["questions"][0]["concept"]
        with self.assertRaisesRegex(quiz_engine.QuizGenerationError, "repeats an underlying concept"):
            quiz_engine.validate_quiz_payload(payload, "DSA", "Arrays and strings", "Beginner", 5)

        payload = {"questions": [make_question(index) for index in range(5)]}
        payload["questions"][0]["concept"] = "binary search time complexity"
        payload["questions"][1]["concept"] = "binary search space complexity"
        payload["questions"][0]["question"] = "What is the time complexity of binary search?"
        payload["questions"][1]["question"] = "What is the space complexity of binary search?"
        self.assertEqual(
            len(quiz_engine.validate_quiz_payload(payload, "DSA", "Arrays and strings", "Beginner", 5)),
            5,
        )

    def test_explanation_is_preserved_through_evaluation(self) -> None:
        explanation = "Option B is correct because this test fixture defines it as the answer."
        result = quiz_engine.evaluate_answers([make_question(0, explanation=explanation)], [1])
        self.assertEqual(result["review"][0]["explanation"], explanation)
        self.assertEqual(result["review"][0]["question_number"], 1)

    def test_duplicate_options_are_rejected(self) -> None:
        payload = {"questions": [make_question(index) for index in range(5)]}
        payload["questions"][0]["options"] = ["same", "same", "other", "last"]
        with self.assertRaisesRegex(quiz_engine.QuizGenerationError, "duplicate answer options"):
            quiz_engine.validate_quiz_payload(payload, "DSA", "Arrays and strings", "Beginner", 5)

    def test_invalid_correct_answer_index_is_rejected(self) -> None:
        payload = {"questions": [make_question(index) for index in range(5)]}
        payload["questions"][0]["correct_option_index"] = 4
        with self.assertRaisesRegex(quiz_engine.QuizGenerationError, "invalid correct answer index"):
            quiz_engine.validate_quiz_payload(payload, "DSA", "Arrays and strings", "Beginner", 5)

    def test_non_integer_correct_answer_index_is_rejected(self) -> None:
        for invalid_index in ("1", 1.0, True):
            with self.subTest(index=invalid_index):
                payload = {"questions": [make_question(index) for index in range(5)]}
                payload["questions"][0]["correct_option_index"] = invalid_index
                with self.assertRaisesRegex(quiz_engine.QuizGenerationError, "invalid correct answer index"):
                    quiz_engine.validate_quiz_payload(payload, "DSA", "Arrays and strings", "Beginner", 5)

    def test_missing_correct_answer_index_is_rejected(self) -> None:
        payload = {"questions": [make_question(index) for index in range(5)]}
        payload["questions"][0].pop("correct_option_index")
        with self.assertRaisesRegex(quiz_engine.QuizGenerationError, "missing required fields"):
            quiz_engine.validate_quiz_payload(payload, "DSA", "Arrays and strings", "Beginner", 5)

    def test_incorrect_question_count_is_rejected(self) -> None:
        payload = {"questions": [make_question(index) for index in range(4)]}
        with self.assertRaisesRegex(quiz_engine.QuizGenerationError, "incorrect question count"):
            quiz_engine.validate_quiz_payload(payload, "DSA", "Arrays and strings", "Beginner", 5)

    def test_score_counts_correct_incorrect_and_unanswered_deterministically(self) -> None:
        questions = [make_question(index) for index in range(3)]
        result = quiz_engine.evaluate_answers(questions, [1, 0, None])
        self.assertEqual(result["total_questions"], 3)
        self.assertEqual(result["correct_answers"], 1)
        self.assertEqual(result["incorrect_answers"], 1)
        self.assertEqual(result["unanswered_questions"], 1)
        self.assertEqual(result["score_percentage"], 33.33)
        self.assertEqual(result["review"][1]["selected_answer"], "Option A")
        self.assertEqual(result["review"][1]["correct_answer"], "Option B")
        self.assertEqual(result["review"][1]["explanation"], questions[1]["explanation"])


class QuizPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "quiz.db"
        self.db_patch = patch.object(database, "DATABASE_PATH", self.db_path)
        self.db_patch.start()
        database.initialize_database()
        connection = database.get_connection()
        try:
            connection.executemany(
                "INSERT INTO students (display_name, email, password_hash) VALUES (?, ?, ?)",
                [("First Student", "first@example.com", "hash"), ("Second Student", "second@example.com", "hash")],
            )
            connection.commit()
        finally:
            connection.close()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_quiz_attempt_persists_and_is_isolated_and_idempotent(self) -> None:
        state = make_quiz_state(1)
        first_result = quiz_engine.submit_quiz(1, state)
        second_result = quiz_engine.submit_quiz(1, state)
        self.assertEqual(first_result, second_result)
        self.assertTrue(state["submitted"])

        attempts = database.get_recent_quiz_attempts(1)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["subject"], "DSA")
        self.assertEqual(attempts[0]["difficulty"], "Beginner")
        self.assertEqual(attempts[0]["total_questions"], 5)
        self.assertEqual(attempts[0]["correct_answers"], 2)
        self.assertEqual(attempts[0]["score"], 40.0)
        self.assertEqual(database.get_recent_quiz_attempts(2), [])
        self.assertEqual(database.get_subject_quiz_stats(2), [])
        stats = database.get_dashboard_stats(1)
        self.assertEqual(stats["quizzes_completed"], 1)
        self.assertEqual(stats["average_score"], 40.0)

    def test_dashboard_overview_uses_one_connection_and_is_student_scoped(self) -> None:
        database.save_quiz_attempt(1, "DSA", "Arrays and strings", "Beginner", 5, 4, 80.0, "overview-1")
        connection = database.get_connection()
        try:
            connection.execute(
                "INSERT INTO learning_progress (student_id, subject, topic, progress_percent) VALUES (?, ?, ?, ?)",
                (1, "DSA", "Arrays", 50),
            )
            connection.commit()
        finally:
            connection.close()
        first = database.get_dashboard_overview(1)
        second = database.get_dashboard_overview(2)
        self.assertEqual(first["stats"]["quizzes_completed"], 1)
        self.assertEqual(first["stats"]["questions_in_quizzes"], 5)
        self.assertEqual(first["progress"][0]["topic"], "Arrays")
        self.assertEqual(len(first["recent_attempts"]), 1)
        self.assertEqual(
            [tuple(row) for row in first["recent_attempts"]],
            [tuple(row) for row in database.get_recent_quiz_attempts(1)],
        )
        self.assertEqual(second["stats"]["quizzes_completed"], 0)
        self.assertEqual(second["stats"]["questions_in_quizzes"], 0)
        self.assertEqual(second["progress"], [])
        self.assertEqual(second["recent_attempts"], [])

    def test_dashboard_shows_empty_states_then_actual_saved_learning_data(self) -> None:
        page_path = Path(__file__).resolve().parent.parent / "pages" / "1_Dashboard.py"
        app = AppTest.from_file(page_path)
        app.session_state["student"] = {
            "id": 1,
            "display_name": "First Student",
            "email": "first@example.com",
        }
        with patch("modules.ai_tutor._request_gemini") as request:
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Welcome back, First" in item.value for item in app.title))
            self.assertTrue(any("No attempts yet" in item.value for item in app.caption))
            self.assertTrue(any("General starting points" in item.value for item in app.caption))
            self.assertEqual(
                [button.label for button in app.button],
                ["Open Learning Path", "Start Practice", "View Subject", "View Subject", "View Subject",
                 "Start Learning", "Start Learning", "Start Learning", "Log out"],
            )

            database.save_quiz_attempt(1, "DSA", "Arrays and strings", "Beginner", 5, 4, 80.0, "dashboard-1")
            database.save_quiz_attempt(1, "DSA", "Arrays and strings", "Beginner", 5, 3, 60.0, "dashboard-2")
            connection = database.get_connection()
            try:
                connection.execute(
                    "INSERT INTO learning_progress (student_id, subject, topic, progress_percent, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (1, "DSA", "Arrays and strings", 50, "in_progress"),
                )
                connection.commit()
            finally:
                connection.close()
            app.run()
            self.assertFalse(app.exception)
            displayed_metrics = {metric.label: metric.value for metric in app.metric}
            self.assertEqual(displayed_metrics["Quizzes attempted"], "2")
            self.assertEqual(displayed_metrics["Average quiz score"], "70.0%")
            self.assertEqual(displayed_metrics["Topics studied"], "1")
            self.assertEqual(displayed_metrics["Overall progress"], "50%")
            rendered_text = " ".join(
                item.value for item in (*app.markdown, *app.caption, *app.subheader)
            )
            self.assertNotIn("Recent activity", rendered_text)
            self.assertNotIn("Recent quiz scores", rendered_text)
            self.assertFalse(any("<svg" in item.value for item in app.markdown))
            request.assert_not_called()

    def test_database_schema_initialization_is_once_per_path_per_process(self) -> None:
        path = self.db_path.parent / "once.db"
        key = str(path.resolve())
        database._initialized_paths.discard(key)
        with patch.object(database, "DATABASE_PATH", path), \
             patch("database.db._initialize_database_schema", wraps=database._initialize_database_schema) as initialize:
            database.initialize_database()
            database.initialize_database()
        self.assertEqual(initialize.call_count, 1)

    def test_quiz_cannot_be_submitted_for_another_student(self) -> None:
        with self.assertRaises(PermissionError):
            quiz_engine.submit_quiz(2, make_quiz_state(1))
        self.assertEqual(database.get_recent_quiz_attempts(1), [])

    def test_practice_ui_keeps_answers_and_locks_after_submission(self) -> None:
        questions = [dict(make_question(index), correct_answer="Option B") for index in range(5)]
        app = AppTest.from_file(Path(__file__).resolve().parent.parent / "pages" / "3_Practice.py")
        app.session_state["student"] = {"id": 1, "display_name": "First Student", "email": "first@example.com"}
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual([item.label for item in app.selectbox], [
            "Subject", "Topic", "Difficulty", "Number of questions",
        ])
        self.assertTrue(any("Ready to test your understanding?" in item.value for item in app.markdown))
        self.assertFalse(any(button.label in {"Previous", "Next", "Submit Quiz"} for button in app.button))

        with patch("modules.quiz_engine.generate_quiz", return_value=questions) as generate:
            next(button for button in app.button if button.label == "Generate Quiz").click().run()
            self.assertEqual(generate.call_count, 1)
        self.assertFalse(app.exception)
        app.run()
        self.assertEqual(generate.call_count, 1, "a Streamlit rerun must reuse the quiz in session state")
        settings_toggle = next(button for button in app.button if button.key == "practice-settings-toggle-button")
        self.assertEqual(settings_toggle.label.strip(), "")
        self.assertEqual(settings_toggle.proto.icon, ":material/settings:")
        self.assertEqual(settings_toggle.proto.help, "Change settings")
        self.assertFalse(any(item.label == "Subject" for item in app.selectbox))
        self.assertTrue(any("Question 1 of 5" in item.text for item in app.progress))
        self.assertTrue(any(question["question"] in item.value for question in questions for item in app.markdown))
        self.assertTrue(next(button for button in app.button if button.label == "Previous").disabled)
        self.assertFalse(next(button for button in app.button if button.label == "Next").disabled)

        app.radio[0].set_value("Option B").run()
        next(button for button in app.button if button.label == "Next").click().run()
        self.assertEqual(app.session_state["practice_quiz_1"]["answers"][0], 1)
        self.assertEqual(app.session_state["practice_quiz_1"]["current_index"], 1)
        next(button for button in app.button if button.label == "Previous").click().run()
        self.assertEqual(app.radio[0].value, "Option B")
        with patch("modules.quiz_engine.generate_quiz") as no_generation:
            next(button for button in app.button if button.key == "practice-settings-toggle-button").click().run()
            self.assertEqual(no_generation.call_count, 0)
        self.assertEqual(app.session_state["practice_quiz_1"]["current_index"], 0)
        self.assertEqual(app.session_state["practice_quiz_1"]["answers"][0], 1)
        self.assertTrue(any(item.label == "Subject" for item in app.selectbox))
        self.assertEqual(app.selectbox(key="practice_subject").value, "DSA")
        self.assertTrue(any(button.label == "Generate New Quiz" for button in app.button))
        next(button for button in app.button if button.key == "practice-settings-toggle-button").click().run()
        self.assertEqual(app.radio[0].value, "Option B")

        next(button for button in app.button if button.label == "Submit Quiz").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.session_state["practice_quiz_1"]["submitted"])
        self.assertFalse(any(button.label == "Submit Quiz" for button in app.button))
        self.assertFalse(any(button.label in {"Previous", "Next"} for button in app.button))
        self.assertFalse(any("unanswered question" in item.value for item in app.warning))
        self.assertFalse(any("Submit with unanswered" in button.label for button in app.button))
        self.assertEqual(next(metric.value for metric in app.metric if metric.label == "Unanswered"), "4")
        self.assertEqual(app.session_state["practice_quiz_1"]["evaluation"]["unanswered_questions"], 4)
        settings_toggle = next(button for button in app.button if button.key == "practice-settings-toggle-button")
        self.assertEqual(settings_toggle.label.strip(), "")
        self.assertEqual(settings_toggle.proto.icon, ":material/settings:")
        self.assertEqual(settings_toggle.proto.help, "Change settings")
        self.assertEqual(len(database.get_recent_quiz_attempts(1)), 1)
        connection = database.get_connection()
        try:
            unanswered_rows = connection.execute(
                "SELECT selected_answer, is_correct FROM quiz_responses "
                "WHERE student_id = 1 AND attempt_id = ? AND selected_answer IS NULL",
                (database.get_recent_quiz_attempts(1)[0]["id"],),
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(len(unanswered_rows), 4)
        self.assertTrue(all(row["selected_answer"] is None and row["is_correct"] is None for row in unanswered_rows))
        self.assertEqual(
            app.session_state["practice_quiz_1"]["evaluation"]["review"][0]["explanation"],
            questions[0]["explanation"],
        )
        self.assertEqual(len(app.expander), 5)  # One explanation expander per question; sidebar usage UI was removed.

    def test_practice_workspace_and_settings_use_responsive_scoped_styles(self) -> None:
        page = Path(__file__).resolve().parent.parent / "pages" / "3_Practice.py"
        source = page.read_text(encoding="utf-8")
        styles = (page.parent.parent / "ui" / "styles.py").read_text(encoding="utf-8")
        self.assertIn('[3, 1], gap="large", vertical_alignment="top"', source)
        self.assertIn('key="practice-empty-layout"', source)
        self.assertIn('key="practice-workspace"', source)
        self.assertIn('key="practice-settings"', source)
        self.assertIn('key="practice-settings-toggle"', source)
        self.assertIn('key="practice-question-navigation"', source)
        self.assertIn('st.session_state["practice_settings_open"]', source)
        self.assertIn('with st.spinner("Generating and validating your quiz...")', source)
        self.assertIn('st.session_state.pop("practice_settings_open", None)', source)
        self.assertIn("st.rerun()", source)
        self.assertIn('key="practice-submit-action"', source)
        self.assertNotIn('st.button("Submit with unanswered questions"', source)
        self.assertNotIn('st.button("Return to quiz"', source)
        workspace_source = source[source.index("def _render_workspace"):source.index("if quiz_state is None:", source.index("def _render_workspace"))]
        self.assertIn("with st.spinner(\"Generating and validating your quiz...\")", workspace_source)
        self.assertIn(".st-key-practice-workspace", styles)
        self.assertIn(".st-key-practice-settings", styles)
        self.assertIn(".st-key-practice-empty-layout", styles)
        self.assertNotIn("min-height:29rem", styles)
        self.assertIn("align-items:stretch!important", styles)
        self.assertIn("flex:1 1 auto", styles)
        self.assertEqual(source.count('horizontal=True, horizontal_alignment="right"'), 2)
        self.assertNotIn("max-width:1080px", styles)
        self.assertIn("width:10rem; max-width:100%", styles)
        self.assertIn('.st-key-practice-settings [data-testid="stButton"] { box-sizing:border-box; width:10rem; max-width:100%; }', styles)
        self.assertIn(".st-key-practice-settings div.stButton > button { box-sizing:border-box; width:100%; min-width:0; max-width:100%; min-height:2.55rem;", styles)
        self.assertIn('key="practice-active-layout"', source)
        self.assertIn('icon=":material/settings:"', source)
        self.assertIn('help="Change settings"', source)
        self.assertIn('" ",', source)
        self.assertNotIn(".st-key-practice-settings-toggle div.stButton > button::before", styles)
        self.assertIn("width:2.65rem; min-width:2.65rem; max-width:2.65rem; height:2.65rem", styles)
        toggle_styles = styles[
            styles.index(".st-key-practice-settings-toggle {"):
            styles.index(".st-key-practice-question-navigation", styles.index(".st-key-practice-settings-toggle {"))
        ]
        self.assertNotIn("font-size:0", toggle_styles)
        self.assertNotIn("overflow:hidden", toggle_styles)
        self.assertIn("align-self:stretch; flex:1 1 auto", styles)
        self.assertIn('[data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"]', styles)
        self.assertIn(".st-key-practice-question-navigation div.stButton > button { box-sizing:border-box; width:6rem; min-width:6rem; max-width:6rem;", styles)
        self.assertIn(".st-key-practice-settings div.stButton > button { box-sizing:border-box; width:100%;", styles)
        self.assertIn(".st-key-practice-submit-action div.stButton > button { box-sizing:border-box; width:12.75rem; min-width:12.75rem;", styles)
        self.assertIn(".st-key-practice-question-navigation div.stButton > button", styles)
        self.assertIn(".st-key-practice-submit-action div.stButton > button", styles)
        self.assertIn('.st-key-practice-workspace [data-testid="stRadio"] [role="radiogroup"] label { box-sizing:border-box;', styles)
        self.assertIn("min-width:100%; max-width:100%", styles)
        self.assertIn("overflow-wrap:anywhere", styles)
        self.assertIn("@media (max-width: 900px)", styles)
        self.assertIn("flex-direction:column", styles)

    def test_practice_ui_exposes_explicit_fresh_quiz_action(self) -> None:
        app = AppTest.from_file(Path(__file__).resolve().parent.parent / "pages" / "3_Practice.py")
        app.session_state["student"] = {"id": 1, "display_name": "First Student", "email": "first@example.com"}
        app.run()
        questions = [dict(make_question(index), correct_answer="Option B") for index in range(5)]
        with patch("modules.quiz_engine.generate_quiz", return_value=questions) as generate:
            next(button for button in app.button if button.label == "Generate New Quiz").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(generate.call_args.kwargs, {"force_new": True})
        self.assertEqual(len(app.session_state["practice_quiz_1"]["answers"]), 5)


    def test_existing_attempt_table_is_migrated_without_losing_rows(self) -> None:
        legacy_path = self.db_path.parent / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute(
                "CREATE TABLE students (id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, email TEXT, password_hash TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute("INSERT INTO students (id, display_name) VALUES (1, 'Legacy Student')")
            connection.execute(
                """CREATE TABLE quiz_attempts (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       student_id INTEGER NOT NULL,
                       subject TEXT NOT NULL,
                       topic TEXT NOT NULL,
                       score REAL NOT NULL,
                       completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                   )"""
            )
            connection.execute(
                "INSERT INTO quiz_attempts (student_id, subject, topic, score) VALUES (1, 'Python', 'Functions', 75)"
            )
            connection.commit()
        finally:
            connection.close()
        with patch.object(database, "DATABASE_PATH", legacy_path):
            database.initialize_database()
            attempts = database.get_recent_quiz_attempts(1)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["score"], 75.0)
        self.assertEqual(attempts[0]["total_questions"], 0)

class QuizCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        quiz_engine.clear_quiz_cache()

    def _payload(self, marker: str = "cached") -> dict:
        questions = [
            make_question(i, question=f"{make_question(i)['question']} ({marker})")
            for i in range(5)
        ]
        return {"questions": questions}

    def test_successful_quiz_cache_hit_and_defensive_copy(self) -> None:
        payload = self._payload()
        before = ai_tutor.get_api_usage_stats()
        with patch("modules.quiz_engine.generate_structured_content", return_value=json.dumps(payload)) as generate:
            first = quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
            first[0]["options"][0] = "local mutation"
            second = quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(second[0]["options"][0], "Option A")
        after = ai_tutor.get_api_usage_stats()
        self.assertEqual(after["quiz_cache_lookups"], before["quiz_cache_lookups"] + 2)
        self.assertEqual(after["cached_quiz_retrievals"], before["cached_quiz_retrievals"] + 1)
        self.assertIsNotNone(after["quiz_cache_hit_rate"])

    def test_cached_quiz_content_contains_no_student_state(self) -> None:
        payload = self._payload()
        with patch("modules.quiz_engine.generate_structured_content", return_value=json.dumps(payload)):
            first_student_quiz = quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
            first_student_answers = [1, None, None, None, None]
            second_student_quiz = quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
            second_student_answers = [None, None, None, None, None]
        self.assertIsNot(first_student_quiz, second_student_quiz)
        self.assertNotIn("student_id", first_student_quiz[0])
        self.assertNotIn("student_id", second_student_quiz[0])
        self.assertEqual(first_student_answers, [1, None, None, None, None])
        self.assertEqual(second_student_answers, [None, None, None, None, None])

    def test_cache_expiration_and_version_invalidation(self) -> None:
        payload = self._payload()
        with patch.object(quiz_engine, "QUIZ_CACHE_TTL_SECONDS", 5), \
             patch("modules.quiz_engine.time.monotonic", side_effect=[10, 10, 10, 20, 20, 20]), \
             patch("modules.quiz_engine.generate_structured_content", return_value=json.dumps(payload)) as generate:
            quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
            quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        self.assertEqual(generate.call_count, 2)

        quiz_engine.clear_quiz_cache()
        with patch("modules.quiz_engine.generate_structured_content", return_value=json.dumps(payload)) as generate:
            quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
            with patch.object(quiz_engine, "QUIZ_PROMPT_SCHEMA_VERSION", "next-version"):
                quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        self.assertEqual(generate.call_count, 2)

    def test_explicit_fresh_request_bypasses_cache(self) -> None:
        first_payload = self._payload("first")
        second_payload = self._payload("second")
        with patch(
            "modules.quiz_engine.generate_structured_content",
            side_effect=[json.dumps(first_payload), json.dumps(second_payload)],
        ) as generate:
            first = quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
            second = quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5, force_new=True)
        self.assertEqual(generate.call_count, 2)
        self.assertNotEqual(first[0]["question"], second[0]["question"])

    def test_invalid_response_is_never_cached(self) -> None:
        with patch(
            "modules.quiz_engine.generate_structured_content",
            side_effect=["not json", json.dumps(self._payload())],
        ) as generate:
            with self.assertRaises(quiz_engine.QuizGenerationError):
                quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
            quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        self.assertEqual(generate.call_count, 2)

    def test_concurrent_identical_requests_share_one_provider_call(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        response_text = json.dumps(self._payload())

        def delayed_generation(*_args):
            entered.set()
            release.wait(timeout=3)
            return response_text

        with patch("modules.quiz_engine.generate_structured_content", side_effect=delayed_generation) as generate:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(quiz_engine.generate_quiz, "DSA", "Arrays and strings", "Beginner", 5)
                self.assertTrue(entered.wait(timeout=2))
                second = pool.submit(quiz_engine.generate_quiz, "DSA", "Arrays and strings", "Beginner", 5)
                release.set()
                self.assertEqual(first.result(timeout=3), second.result(timeout=3))
        self.assertEqual(generate.call_count, 1)



if __name__ == "__main__":
    unittest.main()
