import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "desktop_env" / "evaluators" / "metrics" / "omnic.py"
spec = importlib.util.spec_from_file_location("omnic_metrics", MODULE_PATH)
omnic = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(omnic)


class OmnicMetricTests(unittest.TestCase):
    def _write_temp(self, suffix, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8", newline="")
        with handle:
            handle.write(text)
        return handle.name

    def test_export_table_checks_headers_normalization_and_bounds(self):
        rows = ["wavenumber_cm-1,normalized_absorbance"]
        for wn in range(4000, 648, -4):
            value = 1.0 if wn == 1656 else 0.25
            rows.append(f"{wn},{value}")
        path = self._write_temp(".csv", "\n".join(rows))

        score = omnic.check_omnic_export_table(
            path,
            {
                "extension": ".csv",
                "min_bytes": 100,
                "min_numeric_rows": 300,
                "min_numeric_cols": 2,
                "required_header_keywords": ["wavenumber"],
                "min_wavenumber": 700,
                "max_wavenumber": 3000,
                "normalized_max_ranges": [[0.95, 1.05]],
            },
        )

        self.assertEqual(score, 1.0)

    def test_export_table_rejects_forbidden_hash(self):
        path = self._write_temp(".csv", "wavenumber_cm-1,absorbance\n4000,0.1\n3998,0.2\n")
        digest = omnic._file_sha256(path)

        score = omnic.check_omnic_export_table(
            path,
            {
                "extension": ".csv",
                "min_bytes": 1,
                "forbidden_sha256": [digest],
            },
        )

        self.assertEqual(score, 0.0)

    def test_peak_table_checks_expected_peaks_with_tolerance(self):
        path = self._write_temp(
            ".csv",
            "peak,wavenumber_cm-1,absorbance\n1,2915.7,0.9\n2,2849.4,0.8\n3,1471.8,0.6\n4,1376.9,0.5\n",
        )

        score = omnic.check_omnic_peak_table(
            path,
            {
                "extension": ".csv",
                "min_bytes": 20,
                "min_numeric_rows": 4,
                "min_numeric_cols": 2,
                "include_any_keywords": ["peak"],
                "required_header_keywords": ["wavenumber"],
                "expected_peaks": [2916, 2849, 1472, 1377],
                "tolerance": 2,
            },
        )

        self.assertEqual(score, 1.0)

    def test_fingerprint_region_rejects_full_spectrum_export(self):
        rows = ["wavenumber_cm-1,absorbance"]
        for wn in range(4000, 648, -4):
            rows.append(f"{wn},0.25")
        path = self._write_temp(".csv", "\n".join(rows))

        score = omnic.check_omnic_export_table(
            path,
            {
                "extension": ".csv",
                "min_bytes": 100,
                "min_numeric_rows": 150,
                "min_numeric_cols": 2,
                "required_header_keywords": ["wavenumber"],
                "min_wavenumber": 950,
                "max_wavenumber": 1750,
                "wavenumber_min_at_least": 850,
                "wavenumber_max_at_most": 1850,
            },
        )

        self.assertEqual(score, 0.0)


if __name__ == "__main__":
    unittest.main()
