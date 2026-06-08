import unittest
import sys
import types
from types import SimpleNamespace

gymnasium_stub = types.ModuleType("gymnasium")
gymnasium_stub.Env = object
sys.modules.setdefault("gymnasium", gymnasium_stub)

python_controller_stub = types.ModuleType("desktop_env.controllers.python")
python_controller_stub.PythonController = object
sys.modules.setdefault("desktop_env.controllers.python", python_controller_stub)

setup_controller_stub = types.ModuleType("desktop_env.controllers.setup")
setup_controller_stub.SetupController = object
sys.modules.setdefault("desktop_env.controllers.setup", setup_controller_stub)

metrics_stub = types.ModuleType("desktop_env.evaluators.metrics")
getters_stub = types.ModuleType("desktop_env.evaluators.getters")
evaluators_stub = types.ModuleType("desktop_env.evaluators")
evaluators_stub.metrics = metrics_stub
evaluators_stub.getters = getters_stub
sys.modules.setdefault("desktop_env.evaluators", evaluators_stub)
sys.modules.setdefault("desktop_env.evaluators.metrics", metrics_stub)
sys.modules.setdefault("desktop_env.evaluators.getters", getters_stub)

providers_stub = types.ModuleType("desktop_env.providers")
providers_stub.create_vm_manager_and_provider = lambda *args, **kwargs: (None, None)
sys.modules.setdefault("desktop_env.providers", providers_stub)

maestro_common_utils_stub = types.ModuleType("mm_agents.maestro.utils.common_utils")
maestro_common_utils_stub.screenshot_bytes_to_pil_image = lambda data: data
sys.modules.setdefault(
    "mm_agents.maestro.utils.common_utils",
    maestro_common_utils_stub,
)

from desktop_env.desktop_env import DesktopEnv
from mm_agents.maestro.maestro.Action import TypeText
from mm_agents.maestro.maestro.Backend.PyAutoGUIVMwareBackend import (
    PyAutoGUIVMwareBackend,
)


class OmnicTextClearStrategyTests(unittest.TestCase):
    def test_omnic_snapshot_uses_single_line_strategy(self):
        task_config = {
            "id": "example",
            "snapshot": "omnic",
            "instruction": "Export data from OMNIC",
            "related_apps": [],
            "evaluator": {"func": "check_omnic_export_table"},
        }

        self.assertEqual(
            DesktopEnv._infer_text_clear_strategy(task_config),
            "single_line",
        )

    def test_omnic_related_app_uses_single_line_strategy(self):
        task_config = {
            "id": "example",
            "instruction": "Export data",
            "related_apps": ["omnic"],
            "evaluator": {"func": "check_file_exists"},
        }

        self.assertEqual(
            DesktopEnv._infer_text_clear_strategy(task_config),
            "single_line",
        )

    def test_non_omnic_task_uses_ctrl_a_strategy(self):
        task_config = {
            "id": "example",
            "snapshot": "chrome",
            "instruction": "Search in Chrome",
            "related_apps": ["chrome"],
            "evaluator": {"func": "check_url"},
        }

        self.assertEqual(
            DesktopEnv._infer_text_clear_strategy(task_config),
            "ctrl_a",
        )

    def test_vmware_backend_single_line_overwrite_avoids_ctrl_a(self):
        backend = PyAutoGUIVMwareBackend.__new__(PyAutoGUIVMwareBackend)
        backend.env_controller = SimpleNamespace(text_clear_strategy="single_line")

        command = backend._type(TypeText(text="absorb_export.csv", overwrite=True))

        self.assertIn("pyautogui.press('end')", command)
        self.assertIn("pyautogui.keyDown('shift')", command)
        self.assertIn("pyautogui.press('home')", command)
        self.assertIn("pyautogui.keyUp('shift')", command)
        self.assertNotIn("pyautogui.hotkey('ctrl', 'a'", command)
        self.assertNotIn("pyautogui.press('backspace')", command)
        self.assertTrue(command.rstrip().endswith("pyautogui.write('absorb_export.csv')"))

    def test_vmware_backend_defaults_to_ctrl_a_overwrite(self):
        backend = PyAutoGUIVMwareBackend.__new__(PyAutoGUIVMwareBackend)
        backend.env_controller = SimpleNamespace()

        command = backend._type(TypeText(text="query", overwrite=True))

        self.assertIn("pyautogui.hotkey('ctrl', 'a', interval=0.2)", command)
        self.assertIn("pyautogui.press('backspace')", command)
        self.assertIn("pyautogui.write('query')", command)


if __name__ == "__main__":
    unittest.main()
