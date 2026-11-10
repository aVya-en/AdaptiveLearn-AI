"""Offline tests for the sanitized GroqCloud provider diagnostic utility."""

import os
import sys
import types
import unittest
import httpx
from types import SimpleNamespace
from unittest.mock import Mock, patch
from groq import Groq as RealGroq

from utils import provider_diagnostics


class FakeGroqStatusError(Exception):
    def __init__(self, status_code, body=None):
        super().__init__("synthetic status error")
        self.status_code = status_code
        self.body = body


class FakeGroqConnectionError(Exception):
    pass


def groq_sdk_module(factory):
    module = types.ModuleType("groq")
    module.Groq = factory
    module.APIError = Exception
    module.APIStatusError = FakeGroqStatusError
    module.APIConnectionError = FakeGroqConnectionError
    return module


class ProviderDiagnosticsTests(unittest.TestCase):
    def test_reports_project_groups_and_groq_disabled_without_exposing_values(self):
        environment = {
            "GEMINI_API_KEY_1": "synthetic-key-one",
            "GEMINI_API_KEY_2": "synthetic-key-two",
            "GEMINI_API_KEY_3": "synthetic-key-three",
            "GEMINI_PROJECT_ID_1": "synthetic-project-a",
            "GEMINI_PROJECT_ID_2": "synthetic-project-a",
            "GEMINI_PROJECT_ID_3": "synthetic-project-b",
            "GROQ_API_KEY": "synthetic-groq-key",
            "GROQ_MODEL": "synthetic-model",
            "GROQ_ALLOW_API_USAGE": "false",
        }
        with patch.dict(os.environ, environment, clear=True), \
             patch("utils.provider_diagnostics.load_configuration"), \
             patch("utils.provider_diagnostics._test_gemini_slot", side_effect=["success"] * 3) as gemini, \
             patch("utils.provider_diagnostics._test_groq") as groq:
            report = provider_diagnostics.collect_provider_diagnostics()
        self.assertEqual(gemini.call_count, 3)
        self.assertEqual(report["gemini_slots"][0]["project_group"], "project group 1")
        self.assertEqual(report["gemini_slots"][1]["project_group"], "project group 1")
        self.assertEqual(report["gemini_slots"][2]["project_group"], "project group 2")
        groq.assert_not_called()
        self.assertFalse(report["groq"]["tested"])
        rendered = repr(report)
        for secret in ("synthetic-key-one", "synthetic-project-a", "synthetic-groq-key"):
            self.assertNotIn(secret, rendered)

    def test_groq_only_mode_does_not_send_gemini_requests(self):
        with patch.dict(os.environ, {
            "GEMINI_API_KEY_1": "synthetic-key",
            "GROQ_API_KEY": "synthetic-groq-key",
            "GROQ_ALLOW_API_USAGE": "false",
        }, clear=True), \
             patch("utils.provider_diagnostics.load_configuration"), \
             patch("utils.provider_diagnostics._test_gemini_slot") as gemini:
            report = provider_diagnostics.collect_provider_diagnostics(test_gemini=False)
        gemini.assert_not_called()
        self.assertEqual(report["gemini_slots"][0]["result"], "not tested")

    def test_groq_diagnostic_uses_official_sdk_once_and_sanitizes_error(self):
        status_error = FakeGroqStatusError(400, {"error": {
            "type": "invalid_request_error", "code": "bad_model",
            "message": "Rejected gsk_syntheticsecret123 and private request",
        }})
        client = Mock()
        client.chat.completions.create.side_effect = status_error
        factory = Mock(return_value=client)
        with patch.dict(sys.modules, {"groq": groq_sdk_module(factory)}):
            result = provider_diagnostics._test_groq("gsk_syntheticsecret123", "configured-model")
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["result"], "model/request error")
        self.assertEqual(result["type"], "invalid_request_error")
        self.assertEqual(result["code"], "bad_model")
        self.assertNotIn("gsk_syntheticsecret123", result["message"])
        client.chat.completions.create.assert_called_once_with(
            model="configured-model",
            messages=[{"role": "user", "content": "Reply with OK only."}],
            max_completion_tokens=32,
        )

    def test_sdk_default_base_url_builds_models_path_once_offline(self):
        captured_paths = []
        constructor_kwargs = []

        def handler(request):
            captured_paths.append(request.url.path)
            return httpx.Response(200, json={
                "object": "list",
                "data": [{"id": "openai/gpt-oss-120b", "object": "model", "created": 1, "owned_by": "groq"}],
            })

        def sdk_client(**kwargs):
            constructor_kwargs.append(kwargs)
            http_client = httpx.Client(transport=httpx.MockTransport(handler))
            return RealGroq(**kwargs, http_client=http_client)

        with patch.dict(os.environ, {}, clear=True), \
             patch("groq.Groq", side_effect=sdk_client):
            result = provider_diagnostics._test_groq("synthetic-secret", "openai/gpt-oss-120b")
            model_client = RealGroq(
                api_key="synthetic-secret",
                max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            )
            model_client.models.list()

        self.assertEqual(result, {"result": "success"})
        self.assertNotIn("base_url", constructor_kwargs[0])
        self.assertEqual(captured_paths, [
            "/openai/v1/chat/completions",
            "/openai/v1/models",
        ])
        self.assertTrue(all(path.count("/openai/v1") == 1 for path in captured_paths))


if __name__ == "__main__":
    unittest.main()
