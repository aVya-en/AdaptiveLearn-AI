"""PostgreSQL adapter and schema tests using mocked Psycopg connections."""

import unittest
from unittest.mock import patch

import psycopg

import database.db as database
from database import learning_data
from modules.auth import authenticate_student, register_student


class FakeCursor:
    def __init__(self, row=None):
        self.row = row
        self.execute_calls = []
        self.executemany_calls = []

    def execute(self, query, params=()):
        self.execute_calls.append((query, params))
        return self

    def fetchone(self):
        return self.row

    def executemany(self, query, params):
        self.executemany_calls.append((query, params))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakePostgresConnection:
    def __init__(self, *, fail_on=None, fail_exception=None):
        self.calls = []
        self.batch_calls = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.fail_on = fail_on
        self.fail_exception = fail_exception

    def execute(self, query, params=()):
        self.calls.append((query, params))
        if self.fail_on and self.fail_on in query:
            exception = self.fail_exception or psycopg.OperationalError
            raise exception("mock database failure")
        if "COALESCE(MAX(version), 0)" in query:
            return FakeCursor((0,))
        if "SELECT id FROM quiz_attempts" in query:
            return FakeCursor(database.DatabaseRow(("id",), (42,)))
        if "SELECT id, display_name, email, password_hash" in query:
            return FakeCursor(database.DatabaseRow(
                ("id", "display_name", "email", "password_hash"),
                (7, "Student", "student@example.test", "stored-hash"),
            ))
        return FakeCursor()

    def cursor(self):
        connection = self

        class BatchCursor(FakeCursor):
            def executemany(self, query, params):
                connection.batch_calls.append((query, params))

        return BatchCursor()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class PostgresDatabaseTests(unittest.TestCase):
    def test_connection_normalizes_postgres_url_and_adapts_qmark_parameters(self):
        raw_connection = FakePostgresConnection()
        with patch.object(database, "get_database_url", return_value="postgres://unit-test"), patch(
            "database.db.psycopg.connect", return_value=raw_connection
        ) as connect:
            connection = database.get_connection()
            connection.execute("SELECT id FROM students WHERE email = ?", ("a@example.test",))
            cursor = connection.cursor()
            cursor.execute("SELECT id FROM students WHERE id = ?", (1,))

        connect.assert_called_once()
        self.assertEqual(connect.call_args.args[0], "postgresql://unit-test")
        self.assertEqual(
            raw_connection.calls[0],
            ("SELECT id FROM students WHERE email = %s", ("a@example.test",)),
        )
        self.assertEqual(
            cursor._cursor.execute_calls,
            [("SELECT id FROM students WHERE id = %s", (1,))],
        )
        self.assertTrue(callable(connect.call_args.kwargs["row_factory"]))
        self.assertTrue(raw_connection.closed is False)

    def test_postgres_connection_errors_do_not_expose_the_connection_url(self):
        database_url = "postgresql://unit-test"
        with patch.object(database, "get_database_url", return_value=database_url), patch(
            "database.db.psycopg.connect",
            side_effect=psycopg.OperationalError(f"failed DSN: {database_url}"),
        ), self.assertRaises(database.DatabaseConnectionError) as raised:
            database.get_connection()

        self.assertIn("OperationalError", str(raised.exception))
        self.assertNotIn(database_url, str(raised.exception))

    def test_postgres_authentication_uses_common_connection_and_integrity_errors(self):
        raw_connection = FakePostgresConnection()
        connection = database.PostgresConnection(raw_connection)
        with patch("modules.auth.get_connection", return_value=connection), patch(
            "modules.auth._hash_password", return_value="stored-hash"
        ):
            self.assertTrue(
                register_student(
                    "Student", "STUDENT@example.test", "password123", "password123"
                )[0]
            )
        self.assertIn("INSERT INTO students", raw_connection.calls[0][0])
        self.assertIn("%s", raw_connection.calls[0][0])
        self.assertEqual(raw_connection.commits, 1)

        raw_connection = FakePostgresConnection(
            fail_on="INSERT INTO students", fail_exception=psycopg.IntegrityError
        )
        with patch(
            "modules.auth.get_connection",
            return_value=database.PostgresConnection(raw_connection),
        ), patch("modules.auth._hash_password", return_value="stored-hash"):
            self.assertFalse(
                register_student(
                    "Student", "student@example.test", "password123", "password123"
                )[0]
            )
        self.assertTrue(raw_connection.closed)

        raw_connection = FakePostgresConnection()
        with patch(
            "modules.auth.get_connection",
            return_value=database.PostgresConnection(raw_connection),
        ), patch("modules.auth._verify_password", return_value=True):
            profile = authenticate_student("STUDENT@example.test", "password123")
        self.assertEqual(profile, {
            "id": 7,
            "display_name": "Student",
            "email": "student@example.test",
        })

    def test_postgres_row_supports_named_positional_and_mapping_access(self):
        class Column:
            def __init__(self, name):
                self.name = name

        class Cursor:
            description = (Column("id"), Column("display_name"))

        factory = database._postgres_row_factory(Cursor())
        row = factory((7, "Student"))

        self.assertEqual(row["id"], 7)
        self.assertEqual(row[1], "Student")
        self.assertEqual(tuple(row), (7, "Student"))
        self.assertEqual(dict(row), {"id": 7, "display_name": "Student"})

    def test_postgres_schema_creates_all_tables_constraints_and_indexes_once(self):
        raw_connection = FakePostgresConnection()
        with patch.object(database, "get_database_url", return_value="postgresql://unit-test"), patch(
            "database.db.psycopg.connect", return_value=raw_connection
        ):
            database._initialize_postgresql_schema()

        statements = [query for query, _params in raw_connection.calls]
        schema_sql = "\n".join(statements)
        for table in (
            "students",
            "learning_progress",
            "quiz_attempts",
            "quiz_responses",
            "diagnostic_assessments",
            "adaptive_recommendations",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema_sql)
        self.assertIn("pg_advisory_xact_lock", schema_sql)
        self.assertIn("FOREIGN KEY (attempt_id, student_id)", schema_sql)
        self.assertIn("ON DELETE CASCADE", schema_sql)
        self.assertIn("idx_quiz_attempts_student_subject_topic_completed", schema_sql)
        self.assertIn("INSERT INTO schema_migrations (version) VALUES (1)", schema_sql)
        self.assertEqual(raw_connection.commits, 1)
        self.assertEqual(raw_connection.rollbacks, 0)
        self.assertTrue(raw_connection.closed)

    def test_postgres_schema_failure_rolls_back(self):
        raw_connection = FakePostgresConnection(fail_on="CREATE TABLE IF NOT EXISTS students")
        with patch.object(database, "get_database_url", return_value="postgresql://unit-test"), patch(
            "database.db.psycopg.connect", return_value=raw_connection
        ), self.assertRaises(psycopg.OperationalError):
            database._initialize_postgresql_schema()

        self.assertEqual(raw_connection.commits, 0)
        self.assertEqual(raw_connection.rollbacks, 1)
        self.assertTrue(raw_connection.closed)

    def test_quiz_save_commits_attempt_and_responses_transactionally(self):
        raw_connection = FakePostgresConnection()
        connection = database.PostgresConnection(raw_connection)
        responses = [{
            "question_id": "q0001",
            "subject": "DSA",
            "topic": "Arrays",
            "correct_answer": "B",
            "selected_answer": "B",
            "is_correct": True,
        }]
        with patch.object(database, "get_database_url", return_value="postgresql://unit-test"), patch(
            "database.db.get_connection", return_value=connection
        ), patch("database.learning_data.clear_learning_data_snapshot_cache"):
            attempt_id = database.save_quiz_attempt(
                7, "DSA", "Arrays", "Beginner", 1, 1, 100.0, "postgres-test", responses=responses
            )

        self.assertEqual(attempt_id, 42)
        self.assertEqual(raw_connection.commits, 1)
        self.assertEqual(raw_connection.rollbacks, 0)
        self.assertIn("ON CONFLICT(student_id, attempt_key)", raw_connection.calls[0][0])
        self.assertIn("%s", raw_connection.calls[0][0])
        self.assertEqual(len(raw_connection.batch_calls), 1)
        self.assertIn("ON CONFLICT(attempt_id, question_id)", raw_connection.batch_calls[0][0])

    def test_invalid_quiz_response_rolls_back_postgres_transaction(self):
        raw_connection = FakePostgresConnection()
        connection = database.PostgresConnection(raw_connection)
        with patch.object(database, "get_database_url", return_value="postgresql://unit-test"), patch(
            "database.db.get_connection", return_value=connection
        ), self.assertRaisesRegex(ValueError, "question ID is invalid"):
            database.save_quiz_attempt(
                7,
                "DSA",
                "Arrays",
                "Beginner",
                1,
                1,
                100.0,
                "postgres-invalid",
                responses=[{"question_id": 1}],
            )

        self.assertEqual(raw_connection.commits, 0)
        self.assertEqual(raw_connection.rollbacks, 1)

    def test_postgres_learning_reads_bypass_process_local_cache(self):
        snapshot = {"subjects": [], "concepts": [], "topics": [], "response_metadata": [], "recent_attempts": []}
        overview = {"stats": {}, "progress": [], "recent_attempts": [], "subject_quiz_stats": []}
        with patch.object(database, "get_database_url", return_value="postgresql://unit-test"), patch(
            "database.learning_data._query_learning_data_snapshot", return_value=snapshot
        ) as query_snapshot, patch(
            "database.db.get_dashboard_overview", return_value=overview
        ) as query_overview:
            self.assertIs(learning_data.get_learning_data_snapshot(7), snapshot)
            self.assertEqual(learning_data.get_cached_dashboard_overview(7), overview)

        query_snapshot.assert_called_once_with(7)
        query_overview.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
