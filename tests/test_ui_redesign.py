"""UI smoke checks for the shared Phase 5.4 presentation shell."""

from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


class AdaptiveLearnUiTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
