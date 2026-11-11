"""Gemini tutor tests that never make a network request."""

import os
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import Mock, patch

from google.genai import errors
from streamlit.testing.v1 import AppTest

from modules import ai_tutor
from utils.config import PROJECT_ROOT, get_gemini_api_key, get_gemini_api_keys, get_gemini_model, load_configuration


class GeminiTutorTests(unittest.TestCase):
    def setUp(self) -> None:
        from modules import gemini_credentials
        gemini_credentials.clear_state()
        self.secrets_patch = patch("utils.config._get_streamlit_secret", return_value=None)
        self.secrets_patch.start()

    def tearDown(self) -> None:
        from modules import gemini_credentials
        self.secrets_patch.stop()
        gemini_credentials.clear_state()

    def test_environment_configuration(self) -> None:
        test_environment = {
            "GEMINI_API_KEY_1": "  test-key  ",
            "GEMINI_API_KEY_2": "second-key",
            "GEMINI_API_KEY_3": "",
            "GEMINI_API_KEY": "legacy-key",
            "GEMINI_MODEL": "custom-model",
        }
        with patch.dict(os.environ, test_environment, clear=True), \
             patch("utils.config.load_dotenv") as dotenv:
            load_configuration()
            dotenv.assert_called_once_with(PROJECT_ROOT / ".env")
            self.assertEqual(get_gemini_api_key(), "test-key")
            self.assertEqual(get_gemini_model(), "custom-model")
            self.assertEqual(get_gemini_api_keys(), ["test-key", "second-key", "legacy-key"])
        with patch.dict(os.environ, {
            "GEMINI_API_KEY_1": "", "GEMINI_API_KEY_2": "", "GEMINI_API_KEY_3": "",
            "GEMINI_API_KEY": "", "GEMINI_MODEL": "",
        }, clear=True), patch("utils.config.load_dotenv"):
            load_configuration()
            self.assertIsNone(get_gemini_api_key())
            self.assertEqual(get_gemini_model(), "gemini-3.6-flash")

    def test_lazy_sdk_annotations_resolve_without_module_level_sdk_imports(self) -> None:
        self.assertIn("config", get_type_hints(ai_tutor._request_gemini))
        self.assertIn("error", get_type_hints(ai_tutor._quota_diagnostics))

    def test_instruction_and_contents_include_context_and_history(self) -> None:
        instruction = ai_tutor.build_system_instruction("Python", "Functions", "Beginner", "Asha")
        self.assertIn("Python", instruction)
        self.assertIn("Functions", instruction)
        self.assertIn("Beginner", instruction)
        self.assertIn("Asha", instruction)
        contents = ai_tutor.build_contents(
            [{"role": "user", "content": "What is a function?"}, {"role": "assistant", "content": "A reusable block."}],
            "Can you show one?",
        )
        self.assertEqual([turn["role"] for turn in contents], ["user", "model", "user"])
        self.assertEqual(contents[-1]["parts"][0]["text"], "Can you show one?")

    def test_tutor_context_is_bounded_and_request_fingerprint_tracks_context(self) -> None:
        history = []
        for index in range(12):
            history.extend([
                {"role": "user", "content": f"Question {index}"},
                {"role": "assistant", "content": f"Answer {index}"},
            ])
        contents = ai_tutor.build_contents(history, "Follow up")
        self.assertEqual(len(contents), ai_tutor.MAX_HISTORY_MESSAGES + 1)
        self.assertEqual(contents[0]["parts"][0]["text"], "Question 7")
        first = ai_tutor.tutor_request_fingerprint("Same question", history, "Python", "Functions", "Beginner")
        self.assertEqual(first, ai_tutor.tutor_request_fingerprint("Same question", history, "Python", "Functions", "Beginner"))
        self.assertNotEqual(first, ai_tutor.tutor_request_fingerprint("Same question", history[:-2], "Python", "Functions", "Beginner"))

    def test_usage_monitor_counts_api_and_token_metadata_without_content(self) -> None:
        before = ai_tutor.get_api_usage_stats()
        response = SimpleNamespace(
            text="Private test response",
            usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=7),
        )
        with patch("modules.ai_tutor.genai.Client") as client_factory:
            client = Mock()
            client.models.generate_content.return_value = response
            client_factory.return_value = client
            ai_tutor._request_gemini("test-key", "gemini-3.6-flash", "private prompt")
        after = ai_tutor.get_api_usage_stats()
        self.assertEqual(after["successful_api_calls"], before["successful_api_calls"] + 1)
        self.assertEqual(after["primary_model_requests"], before["primary_model_requests"] + 1)
        self.assertEqual(after["estimated_prompt_tokens"], (before["estimated_prompt_tokens"] or 0) + 12)
        self.assertEqual(after["estimated_response_tokens"], (before["estimated_response_tokens"] or 0) + 7)
        self.assertNotIn("private prompt", str(after))
        self.assertNotIn("Private test response", str(after))

    def test_missing_token_metadata_is_unavailable_and_feature_counts_are_separate(self) -> None:
        reset_counters = {key: 0 for key in ai_tutor._usage_counts}
        with patch.object(ai_tutor, "_usage_counts", reset_counters), patch("modules.ai_tutor.genai.Client") as client_factory:
            self.assertIsNone(ai_tutor.get_api_usage_stats()["estimated_prompt_tokens"])
            self.assertIsNone(ai_tutor.get_api_usage_stats()["average_response_tokens"])
            client = Mock()
            client.models.generate_content.return_value = SimpleNamespace(text="Quiz JSON")
            client_factory.return_value = client
            ai_tutor._request_gemini("test-key", "gemini-3.6-flash", "prompt", feature="quiz")
            after = ai_tutor.get_api_usage_stats()
            self.assertEqual(after["quiz_generation_api_requests"], 1)
            self.assertEqual(after["quiz_generation_successful_calls"], 1)
            self.assertIsNone(after["estimated_prompt_tokens"])
            self.assertIsNone(after["average_prompt_tokens"])
            self.assertNotIn("test-key", str(after))

    def test_token_metadata_is_attributed_to_the_request_feature(self) -> None:
        reset_counters = {key: 0 for key in ai_tutor._usage_counts}
        with patch.object(ai_tutor, "_usage_counts", reset_counters), patch("modules.ai_tutor.genai.Client") as client_factory:
            client = Mock()
            client.models.generate_content.return_value = SimpleNamespace(
                text="Quiz JSON",
                usage_metadata=SimpleNamespace(prompt_token_count=13, candidates_token_count=8),
            )
            client_factory.return_value = client
            ai_tutor._request_gemini("test-key", "gemini-3.6-flash", "prompt", feature="quiz")
            stats = ai_tutor.get_api_usage_stats()
        self.assertEqual(stats["quiz_generation_prompt_tokens_total"], 13)
        self.assertEqual(stats["quiz_generation_response_tokens_total"], 8)
        self.assertEqual(stats["average_quiz_generation_prompt_tokens"], 13)
        self.assertIsNone(stats["average_tutor_prompt_tokens"])

    def test_streamlit_tutor_rerun_does_not_resend_completed_message(self) -> None:
        app = AppTest.from_file(Path(__file__).resolve().parent.parent / "pages" / "2_AI_Tutor.py")
        app.session_state["student"] = {"id": 55, "display_name": "Tutor Test", "email": "tutor@example.com"}
        with patch("modules.ai_tutor.generate_tutor_response", return_value="A function groups reusable code.") as generate:
            app.run()
            self.assertFalse(app.exception)
            app.chat_input[0].set_value("What is a function?").run()
            self.assertFalse(app.exception)
            self.assertEqual(generate.call_count, 1)
            app.run()
            self.assertEqual(generate.call_count, 1)
        conversation = app.session_state[ai_tutor.conversation_key(55)]
        self.assertEqual(len(conversation["messages"]), 2)

    def test_whitespace_tutor_prompt_does_not_create_a_failed_conversation_turn(self) -> None:
        app = AppTest.from_file(Path(__file__).resolve().parent.parent / "pages" / "2_AI_Tutor.py")
        app.session_state["student"] = {"id": 61, "display_name": "Tutor Test", "email": "tutor@example.com"}
        with patch("modules.ai_tutor.generate_tutor_response") as generate:
            app.run()
            app.chat_input[0].set_value("   ").run()

        self.assertFalse(app.exception)
        generate.assert_not_called()
        conversation = app.session_state[ai_tutor.conversation_key(61)]
        self.assertEqual(conversation["messages"], [])
        self.assertNotIn("pending_request", conversation)
        self.assertTrue(any("Enter a question before sending." in item.value for item in app.warning))

    def test_tutor_settings_drawer_toggles_without_request_and_preserves_state(self) -> None:
        app = AppTest.from_file(Path(__file__).resolve().parent.parent / "pages" / "2_AI_Tutor.py")
        app.session_state["student"] = {"id": 57, "display_name": "Tutor Test", "email": "tutor@example.com"}
        with patch("modules.ai_tutor.generate_tutor_response") as generate:
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(app.session_state["tutor_settings_open"])
            self.assertEqual(len(app.selectbox), 3)
            app.selectbox(key="_tutor_subject_widget").select("Python Programming").run()
            self.assertEqual(app.session_state["tutor_subject_selection"], "Python Programming")
            conversation = app.session_state[ai_tutor.conversation_key(57)]
            conversation["messages"].append({"role": "user", "content": "Keep this turn while collapsed."})
            app.run()

            app.button(key="tutor_drawer_close").click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.session_state["tutor_settings_open"])
            self.assertEqual(len(app.selectbox), 0)
            self.assertEqual(len(app.session_state[ai_tutor.conversation_key(57)]["messages"]), 1)

            app.run()
            self.assertFalse(app.exception)
            self.assertFalse(app.session_state["tutor_settings_open"])
            app.button(key="tutor_drawer_open").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.session_state["tutor_settings_open"])
            self.assertEqual(len(app.selectbox), 3)
            self.assertEqual(app.selectbox(key="_tutor_subject_widget").value, "Python Programming")
            self.assertEqual(len(app.session_state[ai_tutor.conversation_key(57)]["messages"]), 1)
            generate.assert_not_called()

    def test_submitted_prompt_is_saved_before_request_and_history_is_not_duplicated(self) -> None:
        app = AppTest.from_file(Path(__file__).resolve().parent.parent / "pages" / "2_AI_Tutor.py")
        app.session_state["student"] = {"id": 58, "display_name": "Tutor Test", "email": "tutor@example.com"}
        observed = {}

        def respond(**kwargs):
            conversation = app.session_state[ai_tutor.conversation_key(58)]
            observed["messages_before_response"] = list(conversation["messages"])
            observed["history"] = kwargs["history"]
            return "Here is a concise explanation."

        with patch("modules.ai_tutor.generate_tutor_response", side_effect=respond) as generate, \
             patch("streamlit.spinner", side_effect=lambda _label: nullcontext()) as spinner:
            app.run()
            app.chat_input[0].set_value("Explain recursion").run()
        self.assertFalse(app.exception)
        self.assertEqual(observed["messages_before_response"][0]["content"], "Explain recursion")
        self.assertEqual(observed["history"], [])
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(len(app.session_state[ai_tutor.conversation_key(58)]["messages"]), 2)
        spinner.assert_called_with("AdaptiveLearn AI is thinking...")

    def test_tutor_failure_keeps_prompt_and_retry_does_not_duplicate_it(self) -> None:
        app = AppTest.from_file(Path(__file__).resolve().parent.parent / "pages" / "2_AI_Tutor.py")
        app.session_state["student"] = {"id": 59, "display_name": "Tutor Test", "email": "tutor@example.com"}
        with patch(
            "modules.ai_tutor.generate_tutor_response",
            side_effect=[ai_tutor.TutorServiceError("Temporarily unavailable"), "Recovered answer"],
        ) as generate:
            app.run()
            app.chat_input[0].set_value("Explain recursion").run()
            self.assertFalse(app.exception)
            conversation = app.session_state[ai_tutor.conversation_key(59)]
            self.assertEqual([item["role"] for item in conversation["messages"]], ["user"])
            app.run()
            self.assertFalse(app.exception)
            app.button(key=f"tutor_retry_59").click().run()
            self.assertFalse(app.exception)
        conversation = app.session_state[ai_tutor.conversation_key(59)]
        self.assertEqual([item["role"] for item in conversation["messages"]], ["user", "assistant"])
        self.assertEqual(generate.call_count, 2)

    def test_sidebar_usage_and_logout_are_present_without_gemini_requests(self) -> None:
        app = AppTest.from_file(Path(__file__).resolve().parent.parent / "app.py")
        app.session_state["student"] = {"id": 60, "display_name": "Sidebar Test", "email": "sidebar@example.com"}
        with patch("modules.ai_tutor._request_gemini") as request:
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any("AdaptiveLearn AI" in str(item.value) for item in app.markdown))
            self.assertFalse(any("Usage details" in str(item.label) for item in app.expander))
            self.assertFalse(any("LOCAL API USAGE" in str(item.value) for item in app.markdown))
            brand_index = next(i for i, item in enumerate(app.markdown) if "AdaptiveLearn AI" in str(item.value))
            account_index = next(i for i, item in enumerate(app.markdown) if "ACCOUNT" in str(item.value))
            self.assertLess(brand_index, account_index)
            sidebar_blocks = list(app.sidebar.children.values())
            self.assertEqual(len(sidebar_blocks), 3)
            brand_block, learn_block, account_block = sidebar_blocks
            self.assertIn("AdaptiveLearn AI", str(next(iter(brand_block.children.values())).value))
            learn_items = list(learn_block.children.values())
            self.assertIn("LEARN", str(learn_items[0].value))
            self.assertEqual(
                [item.label for item in learn_items[1:]],
                ["Dashboard", "Learning Path", "Practice", "AI Tutor", "Progress"],
            )
            self.assertIn("ACCOUNT", str(next(iter(account_block.children.values())).value))
            self.assertTrue(any(item.label == "Log out" for item in app.button))
            app.button(key="adaptivelearn_logout").click().run()
            self.assertIsNone(app.session_state.get("student"))
            self.assertFalse(app.exception)
            request.assert_not_called()

    def test_ordinary_tutor_and_practice_page_reruns_make_no_gemini_request(self) -> None:
        for page in ("2_AI_Tutor.py", "3_Practice.py"):
            with self.subTest(page=page), patch("modules.ai_tutor._request_gemini") as request:
                app = AppTest.from_file(Path(__file__).resolve().parent.parent / "pages" / page)
                app.session_state["student"] = {"id": 56, "display_name": "Nav Test", "email": "nav@example.com"}
                app.run()
                app.run()
                self.assertFalse(app.exception)
                request.assert_not_called()

    def test_conversation_is_per_student_and_resets_when_context_changes(self) -> None:
        state: dict[str, object] = {}
        first = ai_tutor.get_student_conversation(state, 1, "Python", "Functions", "Beginner")
        first["messages"].append({"role": "user", "content": "Private to student one"})
        second = ai_tutor.get_student_conversation(state, 2, "Python", "Functions", "Beginner")
        self.assertEqual(second["messages"], [])
        updated = ai_tutor.get_student_conversation(state, 1, "Python", "Functions", "Advanced")
        self.assertEqual(updated["messages"], [])

    @patch("modules.ai_tutor.get_gemini_api_key", return_value="unit-test-key")
    @patch("modules.ai_tutor.get_gemini_model", return_value="test-model")
    @patch("modules.ai_tutor.genai.Client")
    def test_generate_uses_mocked_gemini_response(self, client_factory: Mock, _model: Mock, _key: Mock) -> None:
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(text="A function is a reusable block.")
        client_factory.return_value = client

        response = ai_tutor.generate_tutor_response(
            "What is a function?", [], "Python Programming", "Functions", "Beginner", "Asha"
        )

        self.assertEqual(response, "A function is a reusable block.")
        client_factory.assert_called_once()
        self.assertEqual(client_factory.call_args.kwargs["api_key"], "unit-test-key")
        self.assertEqual(client_factory.call_args.kwargs["http_options"].timeout, 30_000)
        kwargs = client.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs["model"], "test-model")
        self.assertIn("Beginner", kwargs["config"].system_instruction)

    @patch("modules.ai_tutor.get_gemini_api_key", return_value=None)
    @patch("modules.ai_tutor.genai.Client")
    def test_missing_api_key_fails_without_creating_client(self, client_factory: Mock, _key: Mock) -> None:
        with self.assertRaises(ai_tutor.MissingAPIKeyError):
            ai_tutor.generate_tutor_response("Question?", [], "Python", "Functions", "Beginner")
        client_factory.assert_not_called()

    @patch("modules.ai_tutor.get_gemini_api_key", return_value="unit-test-key")
    def test_api_and_empty_response_fail_clearly(self, _key: Mock) -> None:
        with patch("modules.ai_tutor.genai.Client") as client_factory:
            client = Mock()
            client.models.generate_content.side_effect = errors.APIError(429, {"error": {"message": "limited"}})
            client_factory.return_value = client
            with self.assertRaisesRegex(ai_tutor.TutorServiceError, "rate limit"):
                ai_tutor.generate_tutor_response("Question?", [], "Python", "Functions", "Beginner")

        ai_tutor.gemini_credentials.clear_state()
        with patch("modules.ai_tutor.genai.Client") as client_factory:
            client = Mock()
            client.models.generate_content.return_value = SimpleNamespace(text="  ")
            client_factory.return_value = client
            with self.assertRaisesRegex(ai_tutor.TutorServiceError, "empty response"):
                ai_tutor.generate_tutor_response("Question?", [], "Python", "Functions", "Beginner")

    def test_status_codes_map_to_specific_safe_messages(self) -> None:
        self.assertIn("valid", ai_tutor._api_error_message(403, "model"))
        self.assertIn("model", ai_tutor._api_error_message(404, "bad-model"))
        self.assertIn("quota", ai_tutor._api_error_message(429, "model"))
        self.assertIn("request", ai_tutor._api_error_message(400, "model"))
        self.assertIn("API key", ai_tutor._api_error_message(400, "model", "API_KEY_INVALID"))
        self.assertIn("503", ai_tutor._api_error_message(503, "model"))

    @patch("modules.ai_tutor.get_gemini_api_key", return_value="private-test-key")
    @patch("modules.ai_tutor.genai.Client")
    def test_api_diagnostics_redact_the_configured_key(self, client_factory: Mock, _key: Mock) -> None:
        client = Mock()
        client.models.generate_content.side_effect = errors.APIError(
            403, {"error": {"message": "rejected private-test-key private tutor prompt"}}
        )
        client_factory.return_value = client
        with self.assertLogs(ai_tutor.logger, level="ERROR") as captured:
            with self.assertRaises(ai_tutor.TutorServiceError):
                ai_tutor.generate_tutor_response("private tutor prompt", [], "Python", "Functions", "Beginner")
        self.assertNotIn("private-test-key", "\n".join(captured.output))
        self.assertNotIn("private tutor prompt", "\n".join(captured.output))

    @patch("modules.ai_tutor.load_configuration")
    @patch("modules.ai_tutor.get_gemini_api_key", return_value="unit-test-key")
    @patch("modules.ai_tutor.get_gemini_model", return_value="test-model")
    @patch("modules.ai_tutor.genai.Client")
    def test_connection_test_uses_minimal_prompt_and_returns_real_text(
        self, client_factory: Mock, _model: Mock, _key: Mock, _load: Mock
    ) -> None:
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(text="Gemini connection successful.")
        client_factory.return_value = client
        result = ai_tutor.test_gemini_connection()
        self.assertTrue(result.success)
        self.assertEqual(result.response, "Gemini connection successful.")
        self.assertEqual(str(result), "Gemini connection successful.")
        self.assertEqual(
            client.models.generate_content.call_args.kwargs["contents"],
            "Reply with exactly: Gemini connection successful.",
        )

    def test_connection_test_returns_typed_diagnostics_without_raising(self) -> None:
        failure_cases = [
            ("Gemini is temporarily unavailable (HTTP 503). Try again shortly.", 503, "server_error"),
            ("Gemini quota or rate limit exceeded (429). Check usage.", 429, "quota_or_rate_limit"),
            ("Gemini rejected the API key or its permissions (401/403).", "401/403", "authentication"),
            ("Could not connect to Gemini. Check your network connection and try again.", None, "network_error"),
        ]
        for message, status_code, error_type in failure_cases:
            with self.subTest(error_type=error_type):
                with patch("modules.ai_tutor.load_configuration"), \
                     patch("modules.ai_tutor.get_gemini_api_key", return_value="test-key"), \
                     patch("modules.ai_tutor.get_gemini_model", return_value="test-model"), \
                     patch("modules.ai_tutor._request_gemini", side_effect=ai_tutor.TutorServiceError(message)):
                    result = ai_tutor.test_gemini_connection()
                self.assertFalse(result.success)
                self.assertEqual(result.status_code, status_code)
                self.assertEqual(result.error_type, error_type)
                self.assertEqual(result.message, message)

    @patch("modules.ai_tutor.load_configuration")
    @patch("modules.ai_tutor.get_gemini_api_key", return_value="unit-test-key")
    @patch("modules.ai_tutor.genai.Client")
    def test_model_listing_flags_generate_content_support_without_network(
        self, client_factory: Mock, _key: Mock, _load: Mock
    ) -> None:
        client = Mock()
        client.models.list.return_value = [
            SimpleNamespace(
                name="models/gemini-flash-test",
                display_name="Gemini Flash Test",
                supported_actions=["generateContent", "countTokens"],
            ),
            SimpleNamespace(
                name="models/embedding-test",
                display_name="Embedding Test",
                supported_actions=["embedContent"],
            ),
        ]
        client_factory.return_value = client

        models = ai_tutor.list_available_gemini_models()

        self.assertEqual(len(models), 2)
        self.assertEqual(models[0].name, "models/gemini-flash-test")
        self.assertTrue(models[0].supports_generate_content)
        self.assertFalse(models[1].supports_generate_content)
        client.models.list.assert_called_once_with()

    @patch("modules.ai_tutor.load_configuration")
    @patch("modules.ai_tutor.get_gemini_api_key", return_value=None)
    @patch("modules.ai_tutor.genai.Client")
    def test_model_listing_requires_key_without_creating_client(
        self, client_factory: Mock, _key: Mock, _load: Mock
    ) -> None:
        with self.assertRaises(ai_tutor.MissingAPIKeyError):
            ai_tutor.list_available_gemini_models()
        client_factory.assert_not_called()

    @patch("modules.ai_tutor.get_gemini_api_key", return_value="unit-test-key")
    @patch("modules.ai_tutor.genai.Client")
    def test_network_failure_is_not_replaced_with_a_fake_answer(self, client_factory: Mock, _key: Mock) -> None:
        client = Mock()
        client.models.generate_content.side_effect = OSError("network unavailable")
        client_factory.return_value = client
        with self.assertRaisesRegex(
            ai_tutor.TutorServiceError,
            "Gemini is temporarily unavailable on both gemini-3.6-flash and gemini-3.5-flash",
        ):
            ai_tutor.generate_tutor_response("Question?", [], "Python", "Functions", "Beginner")


if __name__ == "__main__":
    unittest.main()
