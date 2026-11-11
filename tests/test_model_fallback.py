"""Mocked tests for the shared transient-error model fallback path."""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from google.genai import errors
from modules import ai_tutor, quiz_engine


def valid_quiz_response() -> SimpleNamespace:
    questions = []
    stems = [
        "What property does quiz concept {i} demonstrate?",
        "How should quiz concept {i} be applied?",
        "Given quiz concept {i}, which outcome is expected?",
        "Why is quiz concept {i} useful in this case?",
        "Which statement describes quiz concept {i}?",
    ]
    for index in range(5):
        questions.append(
            {
                "question": stems[index].format(i=index),
                "concept": f"distinct quiz concept {index}",
                "options": ["Choice A", "Choice B", "Choice C", "Choice D"],
                "correct_option_index": 2,
                "explanation": "Choice C is correct for this tested concept.",
                "subject": "DSA",
                "topic": "Arrays and strings",
                "difficulty": "Beginner",
            }
        )
    return SimpleNamespace(text=json.dumps({"questions": questions}))


class QuizModelFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        quiz_engine.clear_quiz_cache()
        ai_tutor.gemini_credentials.clear_state()
        self.secrets_patch = patch("utils.config._get_streamlit_secret", return_value=None)
        self.secrets_patch.start()

    def tearDown(self) -> None:
        self.secrets_patch.stop()
        ai_tutor.gemini_credentials.clear_state()

    def generate_with_mocked_requests(self, request_side_effect):
        request_patch = patch("modules.ai_tutor._request_gemini", side_effect=request_side_effect)
        key_patch = patch("modules.ai_tutor.get_gemini_api_key", return_value="test-key")
        model_patch = patch("modules.ai_tutor.get_gemini_model", return_value="gemini-3.6-flash")
        config_patch = patch("modules.ai_tutor.load_configuration")
        sleep_patch = patch("modules.ai_tutor.time.sleep")
        jitter_patch = patch("modules.ai_tutor.random.uniform", side_effect=lambda _low, high: high)
        request = request_patch.start()
        key_patch.start()
        model_patch.start()
        config_patch.start()
        sleep = sleep_patch.start()
        jitter_patch.start()
        self.addCleanup(request_patch.stop)
        self.addCleanup(key_patch.stop)
        self.addCleanup(model_patch.stop)
        self.addCleanup(config_patch.stop)
        self.addCleanup(sleep_patch.stop)
        self.addCleanup(jitter_patch.stop)
        quiz = quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        return quiz, request, sleep

    def test_primary_model_generates_valid_quiz_without_retry(self) -> None:
        quiz, request, sleep = self.generate_with_mocked_requests([valid_quiz_response()])
        self.assertEqual(len(quiz), 5)
        self.assertEqual(quiz[0]["correct_option_index"], 2)
        self.assertEqual(quiz[0]["correct_answer"], "Choice C")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[1], "gemini-3.6-flash")
        sleep.assert_not_called()

    def test_primary_503_uses_one_bounded_jittered_retry_then_fallback_recovers(self) -> None:
        quiz, request, sleep = self.generate_with_mocked_requests(
            [
                ai_tutor.TutorServiceError("HTTP 503", status_code=503),
                ai_tutor.TutorServiceError("HTTP 503", status_code=503),
                valid_quiz_response(),
            ]
        )
        self.assertEqual(len(quiz), 5)
        self.assertEqual([call.args[1] for call in request.call_args_list], [
            "gemini-3.6-flash", "gemini-3.6-flash", "gemini-3.5-flash"
        ])
        self.assertEqual(request.call_args_list[0].args[2], request.call_args_list[2].args[2])
        primary_config = request.call_args_list[0].args[3]
        fallback_config = request.call_args_list[2].args[3]
        self.assertIs(primary_config, fallback_config)
        self.assertEqual(primary_config.response_mime_type, "application/json")
        self.assertIsNotNone(primary_config.response_schema)
        sleep.assert_called_once_with(0.5)

    def test_primary_504_uses_bounded_retries_then_fallback_generates_valid_quiz(self) -> None:
        quiz, request, _sleep = self.generate_with_mocked_requests(
            [
                ai_tutor.TutorServiceError("HTTP 504", status_code=504),
                ai_tutor.TutorServiceError("HTTP 504", status_code=504),
                valid_quiz_response(),
            ]
        )
        self.assertEqual(len(quiz), 5)
        self.assertEqual(request.call_args_list[-1].args[1], "gemini-3.5-flash")

    def test_http_503_is_server_unavailable_not_quota_and_keeps_google_retry_delay(self) -> None:
        provider_error = errors.APIError(503, {
            "error": {
                "status": "UNAVAILABLE",
                "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "2.25s"}],
            }
        })
        client = SimpleNamespace(models=SimpleNamespace(generate_content=unittest.mock.Mock(side_effect=provider_error)))
        types = SimpleNamespace(HttpOptions=lambda **kwargs: kwargs, HttpRetryOptions=lambda **kwargs: kwargs)
        with patch("modules.ai_tutor._load_genai_support", return_value=((errors, types), httpx)), \
             patch("modules.ai_tutor.genai.Client", return_value=client) as client_factory:
            with self.assertRaises(ai_tutor.TutorServiceError) as raised:
                ai_tutor._request_gemini("test-key", "gemini-3.6-flash", "prompt")
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.error_type, "server_error")
        self.assertTrue(raised.exception.transient)
        self.assertIsNone(raised.exception.quota_scope)
        self.assertIsNone(raised.exception.quota_type)
        self.assertEqual(raised.exception.retry_delay_seconds, 2.25)
        self.assertIn("temporarily unavailable", str(raised.exception))
        self.assertEqual(client_factory.call_args.kwargs["http_options"]["retry_options"]["attempts"], 1)
        self.assertEqual(client.models.generate_content.call_count, 1)

    def test_observed_55444_second_project_daily_429_metadata_is_preserved(self) -> None:
        provider_error = errors.APIError(429, {
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "55444s"},
                    {"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                     "metadata": {"quota_limit": "requests_per_day", "quota_metric": "project_requests"}},
                ],
            }
        })
        client = SimpleNamespace(models=SimpleNamespace(generate_content=unittest.mock.Mock(side_effect=provider_error)))
        types = SimpleNamespace(HttpOptions=lambda **kwargs: kwargs, HttpRetryOptions=lambda **kwargs: kwargs)
        with patch("modules.ai_tutor._load_genai_support", return_value=((errors, types), httpx)), \
             patch("modules.ai_tutor.genai.Client", return_value=client):
            with self.assertRaises(ai_tutor.TutorServiceError) as raised:
                ai_tutor._request_gemini("synthetic-key", "gemini-3.6-flash", "synthetic prompt")
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.retry_delay_seconds, 55_444.0)
        self.assertEqual(raised.exception.quota_scope, "shared")
        self.assertEqual(raised.exception.quota_type, "daily")
        self.assertFalse(raised.exception.temporary_rate_limit)

    def test_retry_after_header_is_respected_alongside_google_retry_info(self) -> None:
        provider_error = SimpleNamespace(
            details={"retryDelay": "1.25s"},
            response=SimpleNamespace(headers={"retry-after": "3"}),
        )
        self.assertEqual(ai_tutor._provider_retry_delay(provider_error), 3.0)

    def test_read_timeout_is_classified_and_retried_without_fallback(self) -> None:
        client = SimpleNamespace(models=SimpleNamespace(generate_content=unittest.mock.Mock(
            side_effect=httpx.ReadTimeout("simulated read timeout")
        )))
        types = SimpleNamespace(HttpOptions=lambda **kwargs: kwargs, HttpRetryOptions=lambda **kwargs: kwargs)
        with patch("modules.ai_tutor._load_genai_support", return_value=((errors, types), httpx)), \
             patch("modules.ai_tutor.genai.Client", return_value=client):
            with self.assertRaises(ai_tutor.TutorServiceError) as raised:
                ai_tutor._request_gemini("test-key", "gemini-3.6-flash", "prompt")
        self.assertIsNone(raised.exception.status_code)
        self.assertEqual(raised.exception.error_type, "timeout")
        self.assertTrue(raised.exception.transient)

        with patch("modules.ai_tutor._request_gemini", side_effect=[raised.exception, valid_quiz_response()]) as request, \
             patch("modules.ai_tutor.get_gemini_fallback_model", return_value="gemini-3.5-flash"), \
             patch("modules.ai_tutor.random.uniform", side_effect=lambda _low, high: high), \
             patch("modules.ai_tutor.time.sleep") as sleep:
            response = ai_tutor._request_gemini_with_model_fallback(
                "test-key", "gemini-3.6-flash", "prompt", feature="quiz"
            )
        self.assertIsNotNone(response)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[1].args[1], "gemini-3.6-flash")
        sleep.assert_called_once_with(0.5)

    def test_provider_retry_delay_is_honored_without_jitter(self) -> None:
        temporary = ai_tutor.TutorServiceError(
            "temporarily unavailable", status_code=503, retry_delay_seconds=2.25
        )
        with patch("modules.ai_tutor._request_gemini", side_effect=[temporary, valid_quiz_response()]) as request, \
             patch("modules.ai_tutor.get_gemini_fallback_model", return_value="gemini-3.5-flash"), \
             patch("modules.ai_tutor.random.uniform") as jitter, \
             patch("modules.ai_tutor.time.sleep") as sleep:
            ai_tutor._request_gemini_with_model_fallback("test-key", "gemini-3.6-flash", "prompt")
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(2.25)
        jitter.assert_not_called()

    def test_healthy_fallback_credential_is_attempted_after_first_credential_fails(self) -> None:
        calls = []
        per_key_primary_calls = {"key-one": 0, "key-two": 0}

        def fake_request(api_key, model, *_args, **_kwargs):
            calls.append((api_key, model))
            if model == "gemini-3.6-flash":
                per_key_primary_calls[api_key] += 1
                raise ai_tutor.TutorServiceError("HTTP 503", status_code=503)
            if api_key == "key-one":
                raise ai_tutor.TutorServiceError("HTTP 503", status_code=503)
            return valid_quiz_response()

        with patch.dict(os.environ, {
            "GEMINI_API_KEY_1": "key-one", "GEMINI_PROJECT_ID_1": "project-one",
            "GEMINI_API_KEY_2": "key-two", "GEMINI_PROJECT_ID_2": "project-two",
        }, clear=True), \
             patch("modules.ai_tutor._request_gemini", side_effect=fake_request), \
             patch("modules.ai_tutor.get_gemini_api_key", return_value="key-one"), \
             patch("modules.ai_tutor.get_gemini_model", return_value="gemini-3.6-flash"), \
             patch("modules.ai_tutor.get_gemini_fallback_model", return_value="gemini-3.5-flash"), \
             patch("modules.ai_tutor.load_configuration"), \
             patch("modules.ai_tutor.random.uniform", side_effect=lambda _low, high: high), \
             patch("modules.ai_tutor.time.sleep"):
            response = ai_tutor._request_gemini_with_fallback("key-one", "gemini-3.6-flash", "prompt")
        self.assertIsNotNone(response)
        self.assertEqual(per_key_primary_calls, {"key-one": 2, "key-two": 2})
        self.assertEqual(calls[-1], ("key-two", "gemini-3.5-flash"))

    def test_temporary_429_honors_provider_retry_delay(self) -> None:
        provider_error = errors.APIError(429, {
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "message": "Per-model requests per minute limit exceeded",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "1.25s"},
                    {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "RATE_LIMIT_EXCEEDED",
                     "metadata": {"quota_metric": "generate_content_requests_per_model_per_minute"}},
                ],
            }
        })
        parsed_error = ai_tutor.TutorServiceError(
            "temporary model limit", status_code=429,
            retry_delay_seconds=1.25, quota_scope="model_specific", temporary_rate_limit=True,
        )
        with patch("modules.ai_tutor._request_gemini", side_effect=[parsed_error, valid_quiz_response()]) as request, \
             patch("modules.ai_tutor.get_gemini_api_key", return_value="test-key"), \
             patch("modules.ai_tutor.get_gemini_model", return_value="gemini-3.6-flash"), \
             patch("modules.ai_tutor.load_configuration"), \
             patch("modules.ai_tutor.time.sleep") as sleep:
            quiz = quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        self.assertEqual(len(quiz), 5)
        sleep.assert_called_once_with(1.25)
        self.assertEqual(request.call_count, 2)
        retry_delay, scope, is_temporary = ai_tutor._quota_diagnostics(provider_error)
        self.assertEqual(retry_delay, 1.25)
        self.assertEqual(scope, "model_specific")
        self.assertTrue(is_temporary)

    def test_temporary_model_specific_429_can_fallback_after_retry(self) -> None:
        model_limited = ai_tutor.TutorServiceError(
            "temporary model limit", status_code=429, retry_delay_seconds=0,
            quota_scope="model_specific", temporary_rate_limit=True,
        )
        with patch("modules.ai_tutor._request_gemini", side_effect=[model_limited, model_limited, model_limited, valid_quiz_response()]) as request, \
             patch("modules.ai_tutor.get_gemini_api_key", return_value="test-key"), \
             patch("modules.ai_tutor.get_gemini_model", return_value="gemini-3.6-flash"), \
             patch("modules.ai_tutor.load_configuration"), \
             patch("modules.ai_tutor.time.sleep") as sleep:
            quiz = quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        self.assertEqual(len(quiz), 5)
        self.assertEqual([call.args[1] for call in request.call_args_list], [
            "gemini-3.6-flash", "gemini-3.6-flash", "gemini-3.6-flash", "gemini-3.5-flash"
        ])
        sleep.assert_has_calls([unittest.mock.call(0), unittest.mock.call(0)])

    def test_exhausted_shared_daily_quota_stops_without_retry_or_fallback(self) -> None:
        exhausted = errors.APIError(429, {
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "message": "Daily project request quota exhausted",
                "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                             "metadata": {"quota_limit": "requests_per_day", "quota_metric": "project_requests"}}],
            }
        })
        client = SimpleNamespace(models=SimpleNamespace(generate_content=unittest.mock.Mock(side_effect=exhausted)))
        with patch.dict(os.environ, {
            "GEMINI_API_KEY_1": "test-key", "GEMINI_PROJECT_ID_1": "test-project",
        }, clear=True), \
             patch("modules.ai_tutor.genai.Client", return_value=client), \
             patch("modules.ai_tutor.get_gemini_api_key", return_value="test-key"), \
             patch("modules.ai_tutor.get_gemini_model", return_value="gemini-3.6-flash"), \
             patch("modules.ai_tutor.load_configuration"), \
             patch("modules.ai_tutor.time.sleep") as sleep:
            with self.assertRaises(quiz_engine.QuizGenerationError):
                quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        client.models.generate_content.assert_called_once()
        sleep.assert_not_called()

    def test_shared_quota_429_does_not_switch_models(self) -> None:
        shared_limit = ai_tutor.TutorServiceError(
            "temporary project limit", status_code=429, retry_delay_seconds=0,
            quota_scope="shared", temporary_rate_limit=True,
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "test-key", "GEMINI_PROJECT_ID_1": "test-project"}, clear=True), \
             patch("modules.ai_tutor._request_gemini", side_effect=[shared_limit, shared_limit, shared_limit]) as request, \
             patch("modules.ai_tutor.get_gemini_api_key", return_value="test-key"), \
             patch("modules.ai_tutor.get_gemini_model", return_value="gemini-3.6-flash"), \
             patch("modules.ai_tutor.load_configuration"), \
             patch("modules.ai_tutor.time.sleep"):
            with self.assertRaises(quiz_engine.QuizGenerationError):
                quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        self.assertEqual(request.call_count, 3)
        self.assertTrue(all(call.args[1] == "gemini-3.6-flash" for call in request.call_args_list))

    def test_both_models_failing_returns_error_without_questions(self) -> None:
        per_credential_failures = [
            ai_tutor.TutorServiceError(status, status_code=status_code)
            for _credential in range(3)
            for status, status_code in (("HTTP 503", 503), ("HTTP 503", 503), ("HTTP 504", 504))
        ]
        with patch.dict(os.environ, {
            "GEMINI_API_KEY_1": "test-key",
            "GEMINI_PROJECT_ID_1": "test-project-1",
            "GEMINI_API_KEY_2": "second-test-key",
            "GEMINI_PROJECT_ID_2": "test-project-2",
            "GEMINI_API_KEY_3": "third-test-key",
            "GEMINI_PROJECT_ID_3": "test-project-3",
        }, clear=True), \
             patch("modules.ai_tutor._request_gemini", side_effect=per_credential_failures) as request, \
             patch("modules.ai_tutor.get_gemini_api_key", return_value="test-key"), \
             patch("modules.ai_tutor.get_gemini_model", return_value="gemini-3.6-flash"), \
             patch("modules.ai_tutor.load_configuration"), \
             patch("modules.ai_tutor.time.sleep"):
            with self.assertRaisesRegex(quiz_engine.QuizGenerationError, "both gemini-3.6-flash and gemini-3.5-flash"):
                quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        self.assertEqual(request.call_count, 9)
        self.assertEqual(
            [call.args[0] for call in request.call_args_list],
            ["test-key"] * 3 + ["second-test-key"] * 3 + ["third-test-key"] * 3,
        )
        self.assertEqual(
            [call.args[1] for call in request.call_args_list],
            ["gemini-3.6-flash", "gemini-3.6-flash", "gemini-3.5-flash"] * 3,
        )

    def test_invalid_credentials_do_not_trigger_fallback(self) -> None:
        with patch(
            "modules.ai_tutor._request_gemini",
            side_effect=ai_tutor.TutorServiceError("credentials rejected", status_code=403),
        ) as request, \
             patch("modules.ai_tutor.get_gemini_api_key", return_value="test-key"), \
             patch("modules.ai_tutor.get_gemini_model", return_value="gemini-3.6-flash"), \
             patch("modules.ai_tutor.load_configuration"), \
             patch("modules.ai_tutor.time.sleep") as sleep:
            with self.assertRaises(quiz_engine.QuizGenerationError):
                quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[1], "gemini-3.6-flash")
        sleep.assert_not_called()

    def test_malformed_request_does_not_trigger_fallback(self) -> None:
        with patch(
            "modules.ai_tutor._request_gemini",
            side_effect=ai_tutor.TutorServiceError("invalid request", status_code=400),
        ) as request, \
             patch("modules.ai_tutor.get_gemini_api_key", return_value="test-key"), \
             patch("modules.ai_tutor.get_gemini_model", return_value="gemini-3.6-flash"), \
             patch("modules.ai_tutor.load_configuration"), \
             patch("modules.ai_tutor.time.sleep") as sleep:
            with self.assertRaises(quiz_engine.QuizGenerationError):
                quiz_engine.generate_quiz("DSA", "Arrays and strings", "Beginner", 5)
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
