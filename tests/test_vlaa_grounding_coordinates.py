import io
import unittest

from PIL import Image

from mm_agents.vlaa_gui.agents.grounding import OSWorldACI


def _png_bytes(size):
    image = Image.new("RGB", size, "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _aci(obs, grounding_size=(1000, 1000)):
    aci = OSWorldACI.__new__(OSWorldACI)
    aci.engine_params_for_grounding = {
        "grounding_width": grounding_size[0],
        "grounding_height": grounding_size[1],
    }
    aci.width = 1920
    aci.height = 1080
    aci.resize_width = None
    aci.obs = obs
    aci.last_coordinate_debug = {}
    aci.coords1 = None
    aci.coords2 = None
    return aci


class VLAAGroundingCoordinateTests(unittest.TestCase):
    def test_grounding_coords_scale_to_runtime_screenshot_size(self):
        obs = {"screenshot": _png_bytes((1516, 998))}
        aci = _aci(obs)

        self.assertEqual(aci.resize_coordinates([203, 32]), [308, 32])
        self.assertEqual(aci.last_coordinate_debug["screenshot_size"], [1516, 998])
        self.assertEqual(aci.last_coordinate_debug["grounding_size"], [1000, 1000])
        self.assertEqual(
            aci.last_coordinate_debug["mappings"][0],
            {"grounding_coords": [203, 32], "exec_coords": [308, 32]},
        )

    def test_grounding_coords_are_clamped_to_screenshot_bounds(self):
        obs = {"screenshot": _png_bytes((1516, 998))}
        aci = _aci(obs)

        self.assertEqual(aci.resize_coordinates([1500, -10]), [1515, 0])

    def test_grounding_screenshot_is_resized_to_model_coordinate_space(self):
        obs = {"screenshot": _png_bytes((1516, 998))}
        aci = _aci(obs, grounding_size=(1000, 1000))

        resized, screenshot_size, grounding_size = aci._resize_screenshot_for_grounding(
            obs
        )

        self.assertEqual(screenshot_size, (1516, 998))
        self.assertEqual(grounding_size, (1000, 1000))
        with Image.open(io.BytesIO(resized)) as image:
            self.assertEqual(image.size, (1000, 1000))

    def test_ocr_highlight_coordinates_are_not_scaled_again(self):
        obs = {"screenshot": _png_bytes((1516, 998))}
        aci = _aci(obs)
        aci.coords1 = [203, 32]
        aci.coords2 = [400, 60]

        command = aci.highlight_text_span("start", "end")

        self.assertIn("pyautogui.moveTo(203, 32)", command)
        self.assertIn("pyautogui.dragTo(400, 60", command)


if __name__ == "__main__":
    unittest.main()
