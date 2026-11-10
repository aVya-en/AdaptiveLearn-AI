"""Phase 2 authentication and dashboard regression tests."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import database.db as database
from modules.auth import authenticate_student, register_student


class AuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        self.database_override = patch.object(database, "DATABASE_PATH", self.database_path)
        self.database_override.start()
        database.initialize_database()

    def tearDown(self) -> None:
        self.database_override.stop()
        self.temp_dir.cleanup()

    def test_registration_hashes_password_and_rejects_duplicate_or_mismatch(self) -> None:
        self.assertEqual(
            register_student("Asha Rao", "ASHA@example.com", "correct horse", "correct horse"),
            (True, "Account created. You can now sign in."),
        )
        connection = database.get_connection()
        try:
            stored_hash = connection.execute("SELECT password_hash FROM students").fetchone()[0]
        finally:
            connection.close()
        self.assertNotEqual(stored_hash, "correct horse")
        self.assertTrue(stored_hash.startswith("pbkdf2_sha256$"))
        self.assertFalse(register_student("Other", "asha@example.com", "correct horse", "correct horse")[0])
        self.assertFalse(register_student("Other", "other@example.com", "correct horse", "not matching")[0])

    def test_login_and_student_scoped_dashboard_data(self) -> None:
        register_student("Asha Rao", "asha@example.com", "correct horse", "correct horse")
        first = authenticate_student("ASHA@example.com", "correct horse")
        self.assertIsNotNone(first)
        self.assertIsNone(authenticate_student("asha@example.com", "wrong password"))

        connection = database.get_connection()
        try:
            second_id = connection.execute(
                "INSERT INTO students (display_name, email, password_hash) VALUES (?, ?, ?)",
                ("Dev Patel", "dev@example.com", "test hash"),
            ).lastrowid
            connection.execute(
                "INSERT INTO learning_progress (student_id, subject, topic, progress_percent) VALUES (?, ?, ?, ?)",
                (first["id"], "DSA", "Arrays", 50),
            )
            connection.execute(
                "INSERT INTO quiz_attempts (student_id, subject, topic, score) VALUES (?, ?, ?, ?)",
                (first["id"], "DSA", "Arrays", 80),
            )
            connection.execute(
                "INSERT INTO quiz_attempts (student_id, subject, topic, score) VALUES (?, ?, ?, ?)",
                (second_id, "Python", "Basics", 40),
            )
            connection.commit()
            self.assertEqual(
                database.get_dashboard_stats(first["id"]),
                {"topics_studied": 1, "quizzes_completed": 1, "average_score": 80.0, "overall_progress": 50.0},
            )
            progress_rows = database.get_student_progress(first["id"])
            self.assertEqual(len(progress_rows), 1)
            self.assertEqual(
                {key: progress_rows[0][key] for key in ("subject", "topic", "progress_percent", "status")},
                {"subject": "DSA", "topic": "Arrays", "progress_percent": 50.0, "status": "in_progress"},
            )
            self.assertEqual(database.get_student_progress(second_id), [])
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO quiz_attempts (student_id, subject, topic, score) VALUES (?, ?, ?, ?)",
                    (99999, "DBMS", "Keys", 70),
                )
        finally:
            connection.close()

    def test_streamlit_registration_login_dashboard_and_logout(self) -> None:
        app = AppTest.from_file(Path(__file__).resolve().parent.parent / "app.py").run()
        next(button for button in app.button if button.label == "Create an account").click().run()
        self.assertEqual(app.session_state["auth_screen"], "signup")
        fields = app.text_input
        fields[0].input("Mina Shah")
        fields[1].input("mina@example.com")
        fields[2].input("secure pass 123")
        fields[3].input("secure pass 123")
        next(button for button in app.button if button.label == "Create Account").click().run()
        self.assertTrue(any("Account created" in item.value for item in app.success))

        next(button for button in app.button if button.label == "Sign in").click().run()
        self.assertEqual(app.session_state["auth_screen"], "signin")
        app.text_input[0].input("mina@example.com")
        app.text_input[1].input("secure pass 123")
        next(button for button in app.button if button.label == "Sign In").click().run()
        self.assertEqual(app.session_state["student"]["email"], "mina@example.com")
        self.assertTrue(any("Welcome back, Mina" in item.value for item in app.title))

        next(button for button in app.button if button.label == "Log out").click().run()
        self.assertIsNone(app.session_state["student"])

    def test_protected_page_rejects_missing_or_malformed_student_session(self) -> None:
        page_path = Path(__file__).resolve().parent.parent / "pages" / "4_Progress.py"
        invalid_profiles = (
            None,
            {"id": "not-an-id", "display_name": "Student", "email": "student@example.com"},
            {"id": 1, "display_name": "", "email": "student@example.com"},
            {"id": 1, "display_name": "Student"},
        )
        for profile in invalid_profiles:
            with self.subTest(profile=profile):
                app = AppTest.from_file(page_path)
                if profile is not None:
                    app.session_state["student"] = profile
                app.run()
                self.assertFalse(app.exception)
                self.assertNotIn("student", app.session_state)
                self.assertTrue(any("Sign in" in item.value for item in app.warning))


if __name__ == "__main__":
    unittest.main()
