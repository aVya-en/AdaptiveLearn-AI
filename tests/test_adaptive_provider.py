"""Mocked Groq SDK request construction and adaptive routing tests."""

import sys
import types
import unittest
import os
import httpx
from types import SimpleNamespace
from unittest.mock import Mock, patch
from groq import Groq as RealGroq

from modules import adaptive_provider, ai_tutor


class FakeAPIStatusError(Exception):
    def __init__(self, status_code, retry_after=None, body=None):
        super().__init__("synthetic provider error")
        self.status_code = status_code
        self.response = SimpleNamespace(headers={"retry-after": retry_after} if retry_after else {})
        self.body = body or {"error": {"message": "synthetic provider error"}}


class FakeAPIConnectionError(Exception):
    pass


def groq_sdk_module(client_factory):
    module = types.ModuleType("groq")
    module.Groq = client_factory
    module.APIError = Exception
    module.APIStatusError = FakeAPIStatusError
    module.APIConnectionError = FakeAPIConnectionError
    return module


class GroqRequestTests(unittest.TestCase):
    def setUp(self):
        self.usage_before = dict(adaptive_provider._usage)
        with adaptive_provider._groq_cooldown_lock:
            adaptive_provider._groq_cooldown_until = 0.0

    def tearDown(self):
        adaptive_provider._usage.clear()
        adaptive_provider._usage.update(self.usage_before)
        with adaptive_provider._groq_cooldown_lock:
            adaptive_provider._groq_cooldown_until = 0.0

    def make_client(self, content='{"ok": true}', usage=None):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(**(usage or {})),
        )
        return client

    def test_valid_request_construction_response_parsing_and_usage(self):
        client = self.make_client(usage={"prompt_tokens": 3, "completion_tokens": 2})
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
        factory = Mock(return_value=client)
        input_tokens_before = adaptive_provider._usage["groq_input_tokens"]
        output_tokens_before = adaptive_provider._usage["groq_output_tokens"]
        with patch.dict(sys.modules, {"groq": groq_sdk_module(factory)}), \
             patch("modules.adaptive_provider.get_groq_api_key", return_value="synthetic-secret"), \
             patch("modules.adaptive_provider.get_groq_model", return_value="openai/gpt-oss-120b"):
            result = adaptive_provider._groq_request("safe prompt", schema, "adaptive")

        self.assertEqual(result, '{"ok": true}')
        factory.assert_called_once_with(
            api_key="synthetic-secret",
            timeout=30.0, max_retries=0,
        )
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "openai/gpt-oss-120b")
        self.assertEqual(request["messages"][1], {"role": "user", "content": "safe prompt"})
        self.assertEqual(request["response_format"]["type"], "json_schema")
        sent_schema = request["response_format"]["json_schema"]["schema"]
        self.assertFalse(sent_schema["additionalProperties"])
        self.assertEqual(sent_schema["required"], ["ok"])
        self.assertEqual(sent_schema["properties"], schema["properties"])
        self.assertNotIn("additionalProperties", schema)
        self.assertEqual(request["max_completion_tokens"], 1200)
        self.assertEqual(request["reasoning_effort"], "medium")
        usage = adaptive_provider.get_adaptive_provider_usage()
        self.assertEqual(usage["groq_input_tokens"], input_tokens_before + 3)
        self.assertEqual(usage["groq_output_tokens"], output_tokens_before + 2)

    def test_diagnostic_schema_is_normalized_to_json_schema_type_casing(self):
        client = self.make_client('{"questions": []}')
        factory = Mock(return_value=client)
        schema = {
            "type": "OBJECT",
            "properties": {
                "questions": {
                    "type": "ARRAY",
                    "items": {"type": "OBJECT", "properties": {"concept": {"type": "STRING"}}},
                },
            },
        }
        with patch.dict(sys.modules, {"groq": groq_sdk_module(factory)}), \
             patch("modules.adaptive_provider.get_groq_api_key", return_value="synthetic-secret"), \
             patch("modules.adaptive_provider.get_groq_model", return_value="openai/gpt-oss-120b"):
            adaptive_provider._groq_request("diagnostic prompt", schema, "diagnostic", max_completion_tokens=3500)
        sent = client.chat.completions.create.call_args.kwargs["response_format"]["json_schema"]["schema"]
        self.assertEqual(sent["type"], "object")
        self.assertEqual(sent["properties"]["questions"]["type"], "array")
        self.assertEqual(sent["properties"]["questions"]["items"]["type"], "object")
        self.assertEqual(sent["properties"]["questions"]["items"]["properties"]["concept"]["type"], "string")
        self.assertEqual(client.chat.completions.create.call_args.kwargs["max_completion_tokens"], 3500)

    def test_invalid_schema_is_rejected_before_a_groq_request(self):
        factory = Mock()
        with patch.dict(sys.modules, {"groq": groq_sdk_module(factory)}), \
             patch("modules.adaptive_provider.get_groq_api_key", return_value="synthetic-secret"), \
             patch("modules.adaptive_provider.get_groq_model", return_value="openai/gpt-oss-120b"):
            with self.assertRaises(ai_tutor.TutorServiceError):
                adaptive_provider._groq_request(
                    "prompt", {"type": "OBJECT", "properties": {"bad": {"type": "NOT_A_TYPE"}}}, "diagnostic",
                )
        factory.assert_not_called()

    def test_http_400_logs_sanitized_provider_diagnostics(self):
        body = {"error": {
            "message": "Invalid schema field type OBJECT for student@example.test",
            "type": "invalid_request_error", "code": "invalid_json_schema", "param": "response_format.json_schema.schema.type",
        }}
        factory = Mock(side_effect=FakeAPIStatusError(400, body=body))
        with patch.dict(sys.modules, {"groq": groq_sdk_module(factory)}), \
             patch("modules.adaptive_provider.get_groq_api_key", return_value="gsk_synthetic_secret_value"), \
             patch("modules.adaptive_provider.get_groq_model", return_value="openai/gpt-oss-120b"), \
             self.assertLogs("modules.adaptive_provider", level="ERROR") as captured:
            with self.assertRaises(ai_tutor.TutorServiceError) as raised:
                adaptive_provider._groq_request("Student: student@example.test", {"type": "OBJECT"}, "diagnostic")
        log_output = "\n".join(captured.output)
        self.assertIn("invalid_json_schema", log_output)
        self.assertIn("response_format.json_schema.schema.type", log_output)
        self.assertIn("openai/gpt-oss-120b", log_output)
        self.assertIn("task=diagnostic", log_output)
        self.assertNotIn("student@example.test", log_output)
        self.assertNotIn("gsk_synthetic_secret_value", log_output)
        self.assertEqual(raised.exception.status_code, 400)

    def test_sdk_default_base_url_builds_chat_path_once_offline(self):
        captured_paths = []
        constructor_kwargs = []

        def handler(request):
            captured_paths.append(request.url.path)
            return httpx.Response(200, json={
                "id": "mock-completion", "object": "chat.completion", "created": 1,
                "model": "openai/gpt-oss-120b",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": '{"ok":true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            })

        def sdk_client(**kwargs):
            constructor_kwargs.append(kwargs)
            http_client = httpx.Client(transport=httpx.MockTransport(handler))
            return RealGroq(**kwargs, http_client=http_client)

        with patch.dict(os.environ, {}, clear=True), \
             patch("groq.Groq", side_effect=sdk_client), \
             patch("modules.adaptive_provider.get_groq_api_key", return_value="synthetic-secret"), \
             patch("modules.adaptive_provider.get_groq_model", return_value="openai/gpt-oss-120b"):
            result = adaptive_provider._groq_request("safe prompt", {"type": "object"}, "adaptive")

        self.assertEqual(result, '{"ok":true}')
        self.assertNotIn("base_url", constructor_kwargs[0])
        self.assertEqual(captured_paths, ["/openai/v1/chat/completions"])
        self.assertEqual(captured_paths[0].count("/openai/v1"), 1)

    def test_429_preserves_retry_after_and_sets_cooldown(self):
        factory = Mock(side_effect=FakeAPIStatusError(429, "12"))
        with patch.dict(sys.modules, {"groq": groq_sdk_module(factory)}), \
             patch("modules.adaptive_provider.get_groq_api_key", return_value="synthetic-key"), \
             patch("modules.adaptive_provider.get_groq_model", return_value="model"):
            with self.assertRaises(ai_tutor.TutorServiceError) as raised:
                adaptive_provider._groq_request("prompt", {"type": "object"}, "adaptive")
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.retry_delay_seconds, 12.0)
        self.assertIn("rate limit", str(raised.exception))
        self.assertTrue(adaptive_provider._groq_in_cooldown())

    def test_400_401_503_and_504_are_sanitized_and_classified(self):
        expected = {
            400: "rejected the adaptive request",
            401: "rejected the API key",
            403: "denied permission",
            503: "temporarily unavailable",
            504: "temporarily unavailable",
        }
        for status, phrase in expected.items():
            with self.subTest(status=status), \
                 patch.dict(sys.modules, {"groq": groq_sdk_module(Mock(side_effect=FakeAPIStatusError(status)))}), \
                 patch("modules.adaptive_provider.get_groq_api_key", return_value="synthetic-secret"), \
                 patch("modules.adaptive_provider.get_groq_model", return_value="model"):
                with self.assertRaises(ai_tutor.TutorServiceError) as raised:
                    adaptive_provider._groq_request("prompt", {"type": "object"}, "adaptive")
            self.assertEqual(raised.exception.status_code, status)
            self.assertIn(phrase, str(raised.exception))
            self.assertNotIn("synthetic-secret", str(raised.exception))


class AdaptiveRoutingTests(unittest.TestCase):
    def setUp(self):
        self.usage_before = dict(adaptive_provider._usage)
        with adaptive_provider._groq_cooldown_lock:
            adaptive_provider._groq_cooldown_until = 0.0

    def tearDown(self):
        adaptive_provider._usage.clear()
        adaptive_provider._usage.update(self.usage_before)
        with adaptive_provider._groq_cooldown_lock:
            adaptive_provider._groq_cooldown_until = 0.0

    def test_groq_success_does_not_call_gemini(self):
        with patch("modules.adaptive_provider.load_configuration"), \
             patch("modules.adaptive_provider.groq_api_usage_allowed", return_value=True), \
             patch("modules.adaptive_provider.get_groq_api_key", return_value="synthetic-key"), \
             patch("modules.adaptive_provider._groq_request", return_value='{"ok": true}') as groq, \
             patch("modules.adaptive_provider.generate_structured_content") as gemini:
            result = adaptive_provider._generate_adaptive_uncached("prompt", {"type": "object"}, "adaptive")
        self.assertEqual(result, '{"ok": true}')
        groq.assert_called_once()
        gemini.assert_not_called()

    def test_recoverable_groq_failure_uses_gemini_fallback(self):
        with patch("modules.adaptive_provider.load_configuration"), \
             patch("modules.adaptive_provider.groq_api_usage_allowed", return_value=True), \
             patch("modules.adaptive_provider.get_groq_api_key", return_value="synthetic-key"), \
             patch("modules.adaptive_provider._groq_request", side_effect=ai_tutor.TutorServiceError("down", status_code=503)) as groq, \
             patch("modules.adaptive_provider.generate_structured_content", return_value='{"fallback": true}') as gemini:
            result = adaptive_provider._generate_adaptive_uncached("prompt", {"type": "object"}, "adaptive")
        self.assertEqual(result, '{"fallback": true}')
        groq.assert_called_once()
        gemini.assert_called_once_with("prompt", {"type": "object"}, feature="adaptive")

    def test_groq_authentication_failure_does_not_fallback(self):
        with patch("modules.adaptive_provider.load_configuration"), \
             patch("modules.adaptive_provider.groq_api_usage_allowed", return_value=True), \
             patch("modules.adaptive_provider.get_groq_api_key", return_value="synthetic-key"), \
             patch("modules.adaptive_provider._groq_request", side_effect=ai_tutor.TutorServiceError("unauthorized", status_code=401)), \
             patch("modules.adaptive_provider.generate_structured_content") as gemini:
            with self.assertRaises(ai_tutor.TutorServiceError) as raised:
                adaptive_provider._generate_adaptive_uncached("prompt", {"type": "object"}, "adaptive")
        self.assertEqual(raised.exception.status_code, 401)
        gemini.assert_not_called()

    def test_network_failure_falls_back_and_groq_cooldown_skips_next_request(self):
        network_error = ai_tutor.TutorServiceError("Could not connect to Groq", status_code=None)
        with patch("modules.adaptive_provider.load_configuration"), \
             patch("modules.adaptive_provider.groq_api_usage_allowed", return_value=True), \
             patch("modules.adaptive_provider.get_groq_api_key", return_value="synthetic-key"), \
             patch("modules.adaptive_provider._groq_request", side_effect=network_error) as groq, \
             patch("modules.adaptive_provider.generate_structured_content", return_value='{"ok": true}') as gemini:
            adaptive_provider._generate_adaptive_uncached("one", {"type": "object"}, "adaptive")
            adaptive_provider._set_groq_cooldown(30)
            adaptive_provider._generate_adaptive_uncached("two", {"type": "object"}, "adaptive")
        groq.assert_called_once()
        self.assertEqual(gemini.call_count, 2)


if __name__ == "__main__":
    unittest.main()
