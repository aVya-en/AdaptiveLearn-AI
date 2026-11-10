"""Safe, content-free performance telemetry tests."""

import unittest
from unittest.mock import patch

from utils import performance


class PerformanceTelemetryTests(unittest.TestCase):
    def test_stage_logs_timing_provider_task_and_available_token_counts(self):
        with patch.object(performance, "_ENABLED", True):
            with self.assertLogs("adaptivelearn.performance", level="INFO") as captured:
                with performance.measure_stage(
                    "provider.request",
                    provider="gemini",
                    model="gemini-test-model",
                    task="quiz",
                ) as metrics:
                    metrics["input_tokens"] = 120
                    metrics["output_tokens"] = 55

        message = captured.output[0]
        self.assertIn("provider=gemini", message)
        self.assertIn("model=gemini-test-model", message)
        self.assertIn("task=quiz", message)
        self.assertIn("duration_ms=", message)
        self.assertIn("input_tokens=120", message)
        self.assertIn("output_tokens=55", message)
        self.assertIn("started_at_utc=", message)
        self.assertIn("completed_at_utc=", message)


if __name__ == "__main__":
    unittest.main()
