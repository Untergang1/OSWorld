import unittest
from types import SimpleNamespace

from desktop_env.controllers.setup import SetupController


class SetupHealthCheckTests(unittest.TestCase):
    def setUp(self):
        self.controller = SetupController.__new__(SetupController)

    def test_terminal_not_implemented_is_ready_for_windows_vm(self):
        response = SimpleNamespace(
            status_code=500,
            text="Currently not implemented for platform Windows-10.",
        )

        self.assertTrue(
            self.controller._is_health_response_ready("/terminal", response)
        )

    def test_terminal_other_500_is_not_ready(self):
        response = SimpleNamespace(status_code=500, text="internal server error")

        self.assertFalse(
            self.controller._is_health_response_ready("/terminal", response)
        )

    def test_screenshot_500_is_not_ready(self):
        response = SimpleNamespace(
            status_code=500,
            text="Currently not implemented for platform Windows-10.",
        )

        self.assertFalse(
            self.controller._is_health_response_ready("/screenshot", response)
        )

    def test_status_200_is_ready_for_any_health_endpoint(self):
        response = SimpleNamespace(status_code=200, text="")

        self.assertTrue(
            self.controller._is_health_response_ready("/screenshot", response)
        )
        self.assertTrue(
            self.controller._is_health_response_ready("/terminal", response)
        )


if __name__ == "__main__":
    unittest.main()
