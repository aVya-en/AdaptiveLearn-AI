"""Provider configuration tests for environment variables and Streamlit secrets."""

import os
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from streamlit.errors import StreamlitSecretNotFoundError
from utils import config
from utils.config import (
    get_gemini_api_key,
    get_gemini_api_keys,
    get_gemini_credentials,
    get_gemini_fallback_model,
    get_gemini_max_cooldown_seconds,
    get_gemini_model,
    get_groq_api_key,
    get_groq_model,
    gemini_credential_wait_seconds,
    get_gemini_cooldown_seconds,
    groq_api_usage_allowed,
)


class ProviderSecretsConfigurationTests(unittest.TestCase):
    def test_missing_streamlit_secrets_file_is_handled(self):
        streamlit_module = ModuleType("streamlit")
        streamlit_module.secrets = SimpleNamespace(
            get=Mock(side_effect=StreamlitSecretNotFoundError("missing secrets"))
        )
        errors_module = ModuleType("streamlit.errors")
        errors_module.StreamlitSecretNotFoundError = StreamlitSecretNotFoundError
        with patch.dict(
            sys.modules,
            {"streamlit": streamlit_module, "streamlit.errors": errors_module},
        ):
            self.assertIsNone(config._get_streamlit_secret("GEMINI_API_KEY"))

    def test_provider_settings_load_from_streamlit_secrets(self):
        secrets = {
            "GEMINI_API_KEY_1": "secret-key-one",
            "GEMINI_API_KEY_2": "secret-key-two",
            "GEMINI_API_KEY": "legacy-secret-key",
            "GEMINI_PROJECT_ID_1": "project-one",
            "GEMINI_PROJECT_ID": "legacy-project",
            "GEMINI_MODEL": "secret-gemini-model",
            "GEMINI_FALLBACK_MODEL": "secret-fallback-model",
            "GEMINI_FALLBACK_COOLDOWN_SECONDS": "45",
            "GEMINI_MAX_COOLDOWN_SECONDS": "60",
            "GEMINI_CREDENTIAL_WAIT_SECONDS": "12",
            "GROQ_API_KEY": "secret-groq-key",
            "GROQ_MODEL": "secret-groq-model",
            "GROQ_ALLOW_API_USAGE": "true",
        }
        with patch.dict(os.environ, {}, clear=True), patch(
            "utils.config._get_streamlit_secret", side_effect=secrets.get
        ):
            self.assertEqual(get_gemini_api_key(), "secret-key-one")
            self.assertEqual(
                get_gemini_api_keys(),
                ["secret-key-one", "secret-key-two", "legacy-secret-key"],
            )
            self.assertEqual(
                get_gemini_credentials(),
                [
                    {"key": "secret-key-one", "project_id": "project-one"},
                    {"key": "secret-key-two", "project_id": None},
                    {"key": "legacy-secret-key", "project_id": "legacy-project"},
                ],
            )
            self.assertEqual(get_gemini_model(), "secret-gemini-model")
            self.assertEqual(get_gemini_fallback_model(), "secret-fallback-model")
            self.assertEqual(get_gemini_cooldown_seconds(), 45)
            self.assertEqual(get_gemini_max_cooldown_seconds(), 60)
            self.assertEqual(gemini_credential_wait_seconds(), 12)
            self.assertEqual(get_groq_api_key(), "secret-groq-key")
            self.assertEqual(get_groq_model(), "secret-groq-model")
            self.assertTrue(groq_api_usage_allowed())

    def test_environment_values_take_precedence_over_streamlit_secrets(self):
        environment = {
            "GEMINI_API_KEY_1": "environment-key",
            "GEMINI_MODEL": "environment-gemini-model",
            "GROQ_API_KEY": "environment-groq-key",
            "GROQ_MODEL": "environment-groq-model",
            "GROQ_ALLOW_API_USAGE": "false",
        }
        secrets = {
            "GEMINI_API_KEY_1": "secret-key",
            "GEMINI_MODEL": "secret-gemini-model",
            "GROQ_API_KEY": "secret-groq-key",
            "GROQ_MODEL": "secret-groq-model",
            "GROQ_ALLOW_API_USAGE": "true",
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "utils.config._get_streamlit_secret", side_effect=secrets.get
        ):
            self.assertEqual(get_gemini_api_key(), "environment-key")
            self.assertEqual(get_gemini_model(), "environment-gemini-model")
            self.assertEqual(get_groq_api_key(), "environment-groq-key")
            self.assertEqual(get_groq_model(), "environment-groq-model")
            self.assertFalse(groq_api_usage_allowed())

    def test_missing_secrets_keep_defaults_and_groq_opt_in_disabled(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "utils.config._get_streamlit_secret", return_value=None
        ):
            self.assertIsNone(get_gemini_api_key())
            self.assertEqual(get_gemini_api_keys(), [])
            self.assertEqual(get_gemini_credentials(), [])
            self.assertEqual(get_gemini_model(), "gemini-3.6-flash")
            self.assertEqual(get_gemini_fallback_model(), "gemini-3.5-flash")
            self.assertIsNone(get_groq_api_key())
            self.assertEqual(get_groq_model(), "openai/gpt-oss-120b")
            self.assertFalse(groq_api_usage_allowed())

    def test_groq_key_alone_does_not_enable_provider(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "utils.config._get_streamlit_secret",
            side_effect={"GROQ_API_KEY": "secret-key"}.get,
        ):
            self.assertEqual(get_groq_api_key(), "secret-key")
            self.assertFalse(groq_api_usage_allowed())


if __name__ == "__main__":
    unittest.main()
