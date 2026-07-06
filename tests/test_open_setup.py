import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.setup_import_stubs import install_setup_controller_stubs

install_setup_controller_stubs()

from desktop_env.controllers.setup import SetupController


class OpenSetupTests(unittest.TestCase):
    def setUp(self):
        self.controller = SetupController.__new__(SetupController)
        self.controller.http_server = "http://vm.example"
        self.controller.cache_dir = "."
        self.controller._wait_until_server_ready = lambda: True

    def test_open_setup_sends_optional_window_and_timeout(self):
        calls = []

        def fake_post(url, headers=None, data=None, timeout=None):
            calls.append({
                "url": url,
                "headers": headers,
                "data": json.loads(data),
                "timeout": timeout,
            })
            return SimpleNamespace(status_code=200, text="opened")

        with patch("desktop_env.controllers.setup.requests.post", side_effect=fake_post):
            self.controller._open_setup(
                r"C:\Program Files\Example\Example.exe",
                window_name="Example",
                timeout_seconds=60,
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["url"], "http://vm.example/setup/open_file")
        self.assertEqual(
            calls[0]["data"],
            {
                "path": r"C:\Program Files\Example\Example.exe",
                "window_name": "Example",
                "timeout_seconds": 60,
            },
        )
        self.assertEqual(calls[0]["timeout"], 70)

    def test_open_setup_keeps_legacy_path_only_payload(self):
        calls = []

        def fake_post(url, headers=None, data=None, timeout=None):
            calls.append({"data": json.loads(data), "timeout": timeout})
            return SimpleNamespace(status_code=200, text="opened")

        with patch("desktop_env.controllers.setup.requests.post", side_effect=fake_post):
            self.controller._open_setup(r"C:\Users\User\Workbook.xlsx")

        self.assertEqual(calls[0]["data"], {"path": r"C:\Users\User\Workbook.xlsx"})
        self.assertEqual(calls[0]["timeout"], 1810)


if __name__ == "__main__":
    unittest.main()
