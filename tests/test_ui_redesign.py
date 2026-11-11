"""UI smoke checks for the shared Phase 5.4 presentation shell."""

from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest

from ui.styles import GLOBAL_CSS
from ui.theme import THEME


def _relative_luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return sum(weight * channel for weight, channel in zip((0.2126, 0.7152, 0.0722), linear))


def _contrast_ratio(first: str, second: str) -> float:
    light, dark = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class AdaptiveLearnUiTests(unittest.TestCase):
    def test_light_theme_tokens_are_centralized_and_meet_contrast_targets(self):
        self.assertEqual(THEME["bg"], "#FAFAFA")
        self.assertEqual(THEME["surface"], "#FFFFFF")
        self.assertEqual(THEME["accent"], "#F5C343")
        self.assertIn("--al-font-family:", GLOBAL_CSS)
        self.assertIn("--al-radius-card:", GLOBAL_CSS)
        self.assertIn("--al-shadow-card:", GLOBAL_CSS)
        for foreground, background in (
            ("text", "surface"),
            ("muted", "surface"),
            ("label", "surface"),
            ("link", "bg"),
            ("text", "accent"),
            ("success-text", "success-bg"),
            ("warning-text", "warning-bg"),
            ("error-text", "error-bg"),
        ):
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(
                    _contrast_ratio(THEME[foreground], THEME[background]),
                    4.5,
                )
        self.assertGreaterEqual(
            _contrast_ratio(THEME["control-border"], THEME["surface"]),
            3.0,
        )
        for obsolete_color in ("#0B0F12", "#10171C", "#35D6E8", "#F3F5F7"):
            self.assertNotIn(obsolete_color, GLOBAL_CSS)
        self.assertIn("[data-baseweb=\"popover\"]", GLOBAL_CSS)
        self.assertIn("[data-testid=\"stChatMessage\"]", GLOBAL_CSS)
        self.assertIn(".vg-tooltip", GLOBAL_CSS)

    def test_authentication_page_uses_centered_light_layout_and_masked_password_fields(self):
        page = Path(__file__).resolve().parent.parent / "pages" / "0_Sign_In.py"
        app = AppTest.from_file(page).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.checkbox), 0)
        self.assertTrue(any("AdaptiveLearn AI" in item.value for item in app.markdown))
        self.assertNotIn("auth-visual", " ".join(item.value for item in app.markdown))

        self.assertTrue(any("New to AdaptiveLearn AI?" in item.value for item in app.markdown))
        self.assertTrue(any(item.label == "Create an account" for item in app.button))
        next(item for item in app.button if item.label == "Create an account").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["auth_screen"], "signup")
        self.assertEqual(len(app.success), 0)
        self.assertEqual(len(app.error), 0)
        self.assertEqual([item.label for item in app.text_input], [
            "Full Name", "Email Address", "Password", "Confirm Password",
        ])
        self.assertFalse(any("Show password" in item.label for item in app.checkbox))
        self.assertTrue(any("Already have an account?" in item.value for item in app.markdown))
        self.assertTrue(any(item.label == "Sign in" for item in app.button))
        self.assertIsNone(app.session_state["student"])
        next(item for item in app.button if item.label == "Sign in").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["auth_screen"], "signin")
        self.assertTrue(any("New to AdaptiveLearn AI?" in item.value for item in app.markdown))
        self.assertEqual([item.label for item in app.text_input], ["Email Address", "Password"])

    def test_progress_detail_tile_hit_targets_cover_the_full_tile(self):
        self.assertIn(
            ".st-key-progress-concept-tile .st-key-progress-concept-tile-button",
            GLOBAL_CSS,
        )
        self.assertIn(
            ".st-key-progress-trends-tile .st-key-progress-trends-tile-button",
            GLOBAL_CSS,
        )


if __name__ == "__main__":
    unittest.main()
