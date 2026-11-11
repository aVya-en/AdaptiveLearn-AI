"""Mocked provider infrastructure tests; all provider calls are intercepted."""

import os
import threading
import time
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from modules import adaptive_provider, ai_tutor, gemini_credentials
from utils.config import (
    get_gemini_api_keys, get_gemini_fallback_model,
    get_groq_api_key, get_groq_model, groq_api_usage_allowed,
)


class ProviderInfrastructureTests(unittest.TestCase):
    def setUp(self):
        gemini_credentials.clear_state()
        self.secrets_patch = patch("utils.config._get_streamlit_secret", return_value=None)
        self.secrets_patch.start()

    def tearDown(self):
        self.secrets_patch.stop()
        gemini_credentials.clear_state()

    def test_three_gemini_slots_ignore_empty_and_keep_legacy_compatibility(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": " ",
                                     "GEMINI_API_KEY_3": "three", "GEMINI_API_KEY": "legacy",
                                     "GEMINI_FALLBACK_MODEL": "fallback-x"}):
            self.assertEqual(get_gemini_api_keys(), ["one", "three", "legacy"])
            self.assertEqual(get_gemini_fallback_model(), "fallback-x")

    def test_groq_environment_configuration_is_opt_in_and_configurable(self):
        with patch.dict(os.environ, {
            "GROQ_API_KEY": "synthetic-key",
            "GROQ_MODEL": "openai/gpt-oss-20b",
            "GROQ_ALLOW_API_USAGE": "false",
        }, clear=True):
            self.assertEqual(get_groq_api_key(), "synthetic-key")
            self.assertEqual(get_groq_model(), "openai/gpt-oss-20b")
            self.assertFalse(groq_api_usage_allowed())
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(get_groq_api_key())
            self.assertEqual(get_groq_model(), "openai/gpt-oss-120b")
            self.assertFalse(groq_api_usage_allowed())

    def test_same_exhausted_project_keys_are_temporarily_filtered(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": "two",
                                     "GEMINI_PROJECT_ID_1": "project-a", "GEMINI_PROJECT_ID_2": "project-a"}, clear=True):
            credentials = gemini_credentials.eligible_credentials()
            gemini_credentials.mark_unavailable(credentials[0], 30, scope="project")
            self.assertEqual(gemini_credentials.eligible_credentials(), [])

    def test_recoverable_quota_rotates_to_next_configured_project(self):
        exhausted = ai_tutor.TutorServiceError("limited", status_code=429,
            retry_delay_seconds=20, quota_scope="shared")
        response = SimpleNamespace(text="{}")
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": "two",
                                     "GEMINI_PROJECT_ID_1": "project-a", "GEMINI_PROJECT_ID_2": "project-b"}, clear=True), \
             patch("modules.ai_tutor._request_gemini_with_model_fallback", side_effect=[exhausted, response]) as request:
            result = ai_tutor._request_gemini_with_fallback("one", "model", "prompt")
            self.assertIs(result, response)
            self.assertEqual(request.call_args_list[1].args[0], "two")
            self.assertEqual(gemini_credentials.eligible_credentials()[0]["key"], "two")

    def test_observed_55444_second_shared_project_cooldown_rotates_only_to_other_project(self):
        exhausted = ai_tutor.TutorServiceError(
            "project daily quota", status_code=429, retry_delay_seconds=55_444,
            quota_scope="shared", quota_type="daily",
        )
        response = SimpleNamespace(text="{}")
        environment = {
            "GEMINI_API_KEY_1": "same-project-one", "GEMINI_PROJECT_ID_1": "project-a",
            "GEMINI_API_KEY_2": "same-project-two", "GEMINI_PROJECT_ID_2": "project-a",
            "GEMINI_API_KEY_3": "independent-project", "GEMINI_PROJECT_ID_3": "project-b",
        }
        with patch.dict(os.environ, environment, clear=True), \
             patch("modules.ai_tutor._request_gemini_with_model_fallback", side_effect=[exhausted, response]) as request, \
             patch("modules.gemini_credentials.time.time", return_value=1_000.0):
            result = ai_tutor._request_gemini_with_fallback("same-project-one", "gemini-3.6-flash", "prompt")
            self.assertIs(result, response)
            self.assertEqual(gemini_credentials.eligible_credentials(model="gemini-3.6-flash"), [
                {"key": "independent-project", "project_id": "project-b"}
            ])
            self.assertEqual(gemini_credentials.earliest_retry_time(
                gemini_credentials.configured_credentials()[:2], "gemini-3.6-flash"
            ), 56_444.0)
        self.assertEqual([call.args[0] for call in request.call_args_list], [
            "same-project-one", "independent-project"
        ])
        self.assertIsNone(gemini_credentials.earliest_retry_time(
            gemini_credentials.configured_credentials(), "gemini-3.6-flash"
        ))  # An independent credential is currently available.

    def test_shared_scope_without_project_ids_cools_only_attempted_credential(self):
        limited = ai_tutor.TutorServiceError("project quota", status_code=429,
            retry_delay_seconds=30, quota_scope="shared")
        response = SimpleNamespace(text="ok")
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": "two"}, clear=True), \
             patch("modules.ai_tutor._request_gemini_with_model_fallback", side_effect=[limited, response]) as request:
            result = ai_tutor._request_gemini_with_fallback("one", "model", "prompt")
            self.assertIs(result, response)
            self.assertEqual(gemini_credentials.eligible_credentials(model="model"), [
                {"key": "two", "project_id": None}
            ])
        self.assertEqual([call.args[0] for call in request.call_args_list], ["one", "two"])

    def test_groq_key_does_not_enable_requests_without_opt_in(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "configured", "GROQ_ALLOW_API_USAGE": "false"}, clear=True), \
             patch("modules.adaptive_provider.generate_structured_content", return_value='{"ok": true}') as gemini, \
             patch("modules.adaptive_provider._groq_request") as groq:
            result = adaptive_provider.generate_adaptive_content("prompt", {"type": "object"})
        self.assertEqual(result, '{"ok": true}')
        gemini.assert_called_once()
        groq.assert_not_called()

    def test_groq_recoverable_outage_falls_back_to_gemini(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "configured", "GROQ_ALLOW_API_USAGE": "true"}, clear=True), \
             patch("modules.adaptive_provider._groq_request", side_effect=ai_tutor.TutorServiceError("down", status_code=503)) as groq, \
             patch("modules.adaptive_provider.generate_structured_content", return_value='{"ok": true}') as gemini:
            result = adaptive_provider.generate_adaptive_content("prompt", {"type": "object"})
        self.assertEqual(result, '{"ok": true}')
        groq.assert_called_once()
        gemini.assert_called_once()

    def test_groq_requires_both_key_and_explicit_enablement(self):
        cases = [
            ({"GROQ_API_KEY": "", "GROQ_ALLOW_API_USAGE": "true"}),
            ({"GROQ_API_KEY": "configured", "GROQ_ALLOW_API_USAGE": "false"}),
        ]
        for variables in cases:
            with self.subTest(variables=variables), \
                 patch.dict(os.environ, variables, clear=True), \
                 patch("modules.adaptive_provider._groq_request") as groq_request, \
                 patch("modules.adaptive_provider.generate_structured_content", return_value='{"ok": true}'):
                adaptive_provider.generate_adaptive_content("prompt", {"type": "object"})
                groq_request.assert_not_called()

    def test_gemini_exhaustion_after_groq_outage_is_preserved(self):
        exhausted = ai_tutor.TutorServiceError(
            "All configured Gemini credentials are temporarily unavailable.", status_code=429
        )
        with patch.dict(os.environ, {"GROQ_API_KEY": "configured", "GROQ_ALLOW_API_USAGE": "true"}, clear=True), \
             patch("modules.adaptive_provider._groq_request", side_effect=ai_tutor.TutorServiceError("down", status_code=503)), \
             patch("modules.adaptive_provider.generate_structured_content", side_effect=exhausted):
            with self.assertRaisesRegex(ai_tutor.TutorServiceError, "All configured Gemini credentials"):
                adaptive_provider.generate_adaptive_content("prompt", {"type": "object"})

    def test_groq_authentication_failure_is_not_silently_routed(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "configured", "GROQ_ALLOW_API_USAGE": "true"}, clear=True), \
             patch("modules.adaptive_provider._groq_request", side_effect=ai_tutor.TutorServiceError("unauthorized", status_code=401)), \
             patch("modules.adaptive_provider.generate_structured_content") as gemini:
            with self.assertRaises(ai_tutor.TutorServiceError):
                adaptive_provider.generate_adaptive_content("prompt", {"type": "object"})
        gemini.assert_not_called()

    def test_first_key_success_does_not_call_another_provider_or_key(self):
        response = SimpleNamespace(text="ok")
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": "two"}, clear=True), \
             patch("modules.ai_tutor._request_gemini_with_model_fallback", return_value=response) as request:
            result = ai_tutor._request_gemini_with_fallback("one", "model", "prompt")
        self.assertIs(result, response)
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], "one")

    def test_first_and_second_exhausted_then_third_succeeds(self):
        limited = ai_tutor.TutorServiceError("limited", status_code=429,
            retry_delay_seconds=30, quota_scope="key")
        response = SimpleNamespace(text="ok")
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": "two",
                                     "GEMINI_API_KEY_3": "three"}, clear=True), \
             patch("modules.ai_tutor._request_gemini_with_model_fallback", side_effect=[limited, limited, response]) as request:
            result = ai_tutor._request_gemini_with_fallback("one", "model", "prompt")
        self.assertIs(result, response)
        self.assertEqual([call.args[0] for call in request.call_args_list], ["one", "two", "three"])

    def test_all_three_exhausted_returns_distinct_error(self):
        limited = ai_tutor.TutorServiceError("limited", status_code=429,
            retry_delay_seconds=30, quota_scope="key")
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": "two",
                                     "GEMINI_API_KEY_3": "three"}, clear=True), \
             patch("modules.ai_tutor._request_gemini_with_model_fallback", side_effect=limited) as request:
            with self.assertRaisesRegex(
                ai_tutor.TutorServiceError,
                r"Gemini quota exhaustion \(429\).*All configured Gemini credentials are temporarily unavailable",
            ) as raised:
                ai_tutor._request_gemini_with_fallback("one", "model", "prompt")
            self.assertEqual(raised.exception.status_code, 429)
            self.assertEqual(raised.exception.quota_scope, "key")
        self.assertEqual([call.args[0] for call in request.call_args_list], ["one", "two", "three"])

    def test_all_three_same_project_exhaustion_only_calls_project_once(self):
        limited = ai_tutor.TutorServiceError("limited", status_code=429,
            retry_delay_seconds=30, quota_scope="shared")
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": "two",
                                     "GEMINI_API_KEY_3": "three", "GEMINI_PROJECT_ID_1": "p",
                                     "GEMINI_PROJECT_ID_2": "p", "GEMINI_PROJECT_ID_3": "p"}, clear=True), \
             patch("modules.ai_tutor._request_gemini_with_model_fallback", side_effect=limited) as request:
            with self.assertRaisesRegex(
                ai_tutor.TutorServiceError,
                r"Gemini quota exhaustion \(429\).*All configured Gemini credentials",
            ) as raised:
                ai_tutor._request_gemini_with_fallback("one", "model", "prompt")
            self.assertEqual(raised.exception.status_code, 429)
            self.assertEqual(raised.exception.quota_scope, "shared")
        request.assert_called_once()

    def test_shared_quota_without_project_ids_does_not_assume_credentials_share_bucket(self):
        limited = ai_tutor.TutorServiceError("project quota", status_code=429,
            retry_delay_seconds=30, quota_scope="shared")
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": "two"}, clear=True), \
             patch("modules.ai_tutor._request_gemini_with_model_fallback", side_effect=limited) as request:
            with self.assertRaisesRegex(ai_tutor.TutorServiceError, "Project identity is not configured"):
                ai_tutor._request_gemini_with_fallback("one", "model", "prompt")
        self.assertEqual([call.args[0] for call in request.call_args_list], ["one", "two"])

    def test_cooldown_expiry_restores_credential_eligibility(self):
        credential = {"key": "one", "project_id": None}
        with patch("modules.gemini_credentials.time.time", side_effect=[100.0, 103.0]):
            gemini_credentials.mark_unavailable(credential, 2, scope="key")
            available = gemini_credentials.eligible_credentials("one")
        self.assertEqual(available[0]["key"], "one")

    def test_missing_retry_delay_uses_exponential_cooldown_with_cap(self):
        credential = {"key": "one", "project_id": None}
        with patch("modules.gemini_credentials.get_gemini_cooldown_seconds", return_value=2), \
             patch("modules.gemini_credentials.get_gemini_max_cooldown_seconds", return_value=3), \
             patch("modules.gemini_credentials.time.time", return_value=100.0):
            first_expiry = gemini_credentials.mark_unavailable(credential, None, scope="key")
            second_expiry = gemini_credentials.mark_unavailable(credential, None, scope="key")
        self.assertEqual(first_expiry, 102.0)
        self.assertEqual(second_expiry, 103.0)

    def test_earliest_retry_uses_each_credential_latest_applicable_expiry(self):
        rows = [
            {"key": "one", "project_id": "project-a"},
            {"key": "two", "project_id": "project-b"},
        ]
        with patch("modules.gemini_credentials.time.time", return_value=100.0):
            gemini_credentials.mark_unavailable(rows[0], 20, scope="key")
            gemini_credentials.mark_unavailable(rows[0], 40, scope="project")
            gemini_credentials.mark_unavailable(rows[1], 30, scope="key")
            self.assertEqual(gemini_credentials.earliest_retry_time(rows), 130.0)

    def test_quota_diagnostics_distinguish_project_model_rpm_tpm_and_daily(self):
        cases = [
            ({"quota_limit": "requests_per_model_per_minute", "quota_metric": "model"}, "model_specific", "request_per_minute"),
            ({"quota_limit": "requests_per_minute", "quota_metric": "project_requests"}, "shared", "request_per_minute"),
            ({"quota_limit": "tokens_per_minute", "quota_metric": "project_tokens"}, "shared", "token_per_minute"),
            ({"quota_limit": "requests_per_day", "quota_metric": "project_requests"}, "shared", "daily"),
        ]
        for details, expected_scope, expected_type in cases:
            retry, scope, _temporary = ai_tutor._quota_diagnostics(SimpleNamespace(details=details))
            self.assertEqual(scope, expected_scope)
            self.assertEqual(ai_tutor._quota_type(details), expected_type)
            self.assertIsNone(retry)

    def test_missing_keys_invalid_credentials_and_bad_requests_do_not_rotate(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(gemini_credentials.reserve_credential())
        for status in (400, 401, 403):
            gemini_credentials.clear_state()
            with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": "two"}, clear=True), \
                 patch("modules.ai_tutor._request_gemini_with_model_fallback",
                       side_effect=ai_tutor.TutorServiceError("not recoverable", status_code=status)) as request:
                with self.assertRaises(ai_tutor.TutorServiceError):
                    ai_tutor._request_gemini_with_fallback("one", "model", "prompt")
            request.assert_called_once()

    def test_transient_server_failure_tries_each_configured_credential_once(self):
        unavailable = ai_tutor.TutorServiceError("temporarily unavailable", status_code=503)
        with patch.dict(os.environ, {
            "GEMINI_API_KEY_1": "key-one", "GEMINI_PROJECT_ID_1": "project-one",
            "GEMINI_API_KEY_2": "key-two", "GEMINI_PROJECT_ID_2": "project-two",
            "GEMINI_API_KEY_3": "key-three", "GEMINI_PROJECT_ID_3": "project-three",
        }, clear=True), \
             patch("modules.ai_tutor._request_gemini_with_model_fallback", side_effect=unavailable) as request:
            with self.assertRaises(ai_tutor.TutorServiceError):
                ai_tutor._request_gemini_with_fallback("key-one", "model", "prompt")
        self.assertEqual([call.args[0] for call in request.call_args_list], ["key-one", "key-two", "key-three"])

    def test_model_specific_exhaustion_leaves_another_model_eligible(self):
        limited = ai_tutor.TutorServiceError("model limited", status_code=429,
            retry_delay_seconds=30, quota_scope="model_specific")
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one"}, clear=True), \
             patch("modules.ai_tutor._request_gemini_with_model_fallback", side_effect=limited), \
             patch("modules.gemini_credentials.time.time", return_value=1000.0):
            with self.assertRaises(ai_tutor.TutorServiceError):
                ai_tutor._request_gemini_with_fallback("one", "model-a", "prompt")
            self.assertEqual(gemini_credentials.eligible_credentials("one", "model-b")[0]["key"], "one")
            self.assertEqual(gemini_credentials.eligible_credentials("one", "model-a"), [])

    def test_project_model_quota_blocks_same_project_only_for_that_model(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": "two",
                                     "GEMINI_PROJECT_ID_1": "shared", "GEMINI_PROJECT_ID_2": "shared"}, clear=True):
            first = gemini_credentials.eligible_credentials()[0]
            gemini_credentials.mark_unavailable(first, 30, scope="project_model", model="model-a")
            self.assertEqual(gemini_credentials.eligible_credentials(model="model-a"), [])
            self.assertEqual(len(gemini_credentials.eligible_credentials(model="model-b")), 2)

    def test_concurrent_reservations_choose_distinct_keys_and_release(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": "two"}, clear=True):
            with ThreadPoolExecutor(max_workers=2) as pool:
                leases = list(pool.map(lambda _n: gemini_credentials.reserve_credential(wait_timeout=0), (1, 2)))
            self.assertEqual({row["key"] for row in leases if row}, {"one", "two"})
            for lease in leases:
                gemini_credentials.release_credential(lease)
            self.assertEqual(len(gemini_credentials.eligible_credentials()), 2)

    def test_waiting_request_uses_another_key_after_reserved_key_is_exhausted(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_2": "two"}, clear=True):
            first = gemini_credentials.reserve_credential(wait_timeout=0)
            second = gemini_credentials.reserve_credential(excluded_keys={"one"}, wait_timeout=0)
            with ThreadPoolExecutor(max_workers=1) as pool:
                waiting = pool.submit(gemini_credentials.reserve_credential, model="model", wait_timeout=1)
                time.sleep(0.05)
                gemini_credentials.mark_unavailable(first, 30, scope="key")
                gemini_credentials.release_credential(second)
                selected = waiting.result(timeout=1)
            self.assertEqual(selected["key"], "two")
            gemini_credentials.release_credential(selected)

    def test_unexpected_request_exception_releases_reservation(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY_1": "one"}, clear=True), \
             patch("modules.ai_tutor._request_gemini_with_model_fallback", side_effect=RuntimeError("local failure")):
            with self.assertRaisesRegex(RuntimeError, "local failure"):
                ai_tutor._request_gemini_with_fallback("one", "model", "prompt")
            lease = gemini_credentials.reserve_credential("one", wait_timeout=0)
            self.assertEqual(lease["key"], "one")
            gemini_credentials.release_credential(lease)

    def test_identical_adaptive_requests_coalesce_per_student_and_not_across_students(self):
        started = threading.Event()
        follower_waiting = threading.Event()
        finish = threading.Event()

        def slow_call(*_args, **_kwargs):
            started.set()
            finish.wait(2)
            return '{"ok": true}'

        original_result = Future.result

        def tracked_result(future, *args, **kwargs):
            follower_waiting.set()
            return original_result(future, *args, **kwargs)

        with patch("modules.adaptive_provider._generate_adaptive_uncached", side_effect=slow_call) as generate, \
             patch.object(Future, "result", tracked_result), \
             ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(adaptive_provider.generate_adaptive_content, "p", {"type": "object"}, "adaptive", student_scope=1)
            self.assertTrue(started.wait(1))
            second = pool.submit(adaptive_provider.generate_adaptive_content, "p", {"type": "object"}, "adaptive", student_scope=1)
            self.assertTrue(follower_waiting.wait(1))
            finish.set()
            self.assertEqual(first.result(timeout=2), second.result(timeout=2))
            self.assertEqual(generate.call_count, 1)
            self.assertEqual(adaptive_provider.generate_adaptive_content(
                "p", {"type": "object"}, "adaptive", student_scope=2
            ), '{"ok": true}')
            self.assertEqual(generate.call_count, 2)


if __name__ == "__main__":
    unittest.main()
