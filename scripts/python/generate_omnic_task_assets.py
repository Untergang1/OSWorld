r"""Generate deterministic synthetic FTIR assets for Windows OMNIC tasks.

The assets are small CSV and JCAMP-DX text spectra that can be copied to a
Windows VM snapshot at C:\Users\User\OMNIC_data.
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evaluation_examples" / "omnic_assets"
RNG = random.Random(20260701)


@dataclass(frozen=True)
class Peak:
    center: float
    width: float
    amplitude: float


def gaussian(x: float, center: float, width: float, amplitude: float) -> float:
    return amplitude * math.exp(-0.5 * ((x - center) / width) ** 2)


def spectrum(
    peaks: Sequence[Peak],
    *,
    start: int = 4000,
    stop: int = 650,
    step: int = -2,
    baseline: float = 0.025,
    slope: float = 0.018,
    ripple: float = 0.004,
    noise: float = 0.0015,
) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    count = int((stop - start) / step) + 1
    for index in range(count):
        wn = start + index * step
        fraction = (start - wn) / (start - stop)
        y = baseline + slope * fraction + ripple * math.sin(wn / 115.0)
        y += sum(gaussian(wn, peak.center, peak.width, peak.amplitude) for peak in peaks)
        y += RNG.uniform(-noise, noise)
        rows.append((float(wn), max(y, 0.0)))
    return rows


def normalize(rows: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    materialized = list(rows)
    y_max = max(y for _, y in materialized)
    return [(x, y / y_max) for x, y in materialized]


def ensure_out() -> None:
    if OUT.exists():
        for path in sorted(OUT.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    OUT.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, title: str, rows: Sequence[tuple[float, float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_name", title])
        writer.writerow(["wavenumber_cm-1", "absorbance"])
        for x, y in rows:
            writer.writerow([f"{x:.2f}", f"{y:.6f}"])


def write_jdx(path: Path, title: str, rows: Sequence[tuple[float, float]]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write(f"##TITLE={title}\n")
        handle.write("##JCAMP-DX=5.00\n")
        handle.write("##DATA TYPE=INFRARED SPECTRUM\n")
        handle.write("##ORIGIN=OSWorld synthetic benchmark\n")
        handle.write("##OWNER=OSWorld\n")
        handle.write("##XUNITS=1/CM\n")
        handle.write("##YUNITS=ABSORBANCE\n")
        handle.write(f"##FIRSTX={rows[0][0]:.2f}\n")
        handle.write(f"##LASTX={rows[-1][0]:.2f}\n")
        handle.write(f"##NPOINTS={len(rows)}\n")
        handle.write("##XYPOINTS=(XY..XY)\n")
        for x, y in rows:
            handle.write(f"{x:.2f} {y:.6f}\n")
        handle.write("##END=\n")


def write_spectrum_pair(stem: str, title: str, rows: Sequence[tuple[float, float]]) -> None:
    write_csv(OUT / f"{stem}.csv", title, rows)
    write_jdx(OUT / f"{stem}.jdx", title, rows)


def generate_assets() -> None:
    polymer = spectrum(
        [
            Peak(2916, 18, 0.58),
            Peak(2849, 16, 0.47),
            Peak(1734, 24, 0.18),
            Peak(1472, 15, 0.38),
            Peak(1377, 16, 0.29),
            Peak(1167, 18, 0.24),
            Peak(998, 15, 0.19),
            Peak(721, 12, 0.17),
        ],
        baseline=0.02,
        slope=0.012,
    )
    write_spectrum_pair("polymer_film", "OMNIC synthetic polymer film ATR", polymer)

    protein = spectrum(
        [
            Peak(3288, 95, 0.22),
            Peak(2958, 28, 0.10),
            Peak(1654, 32, 0.60),
            Peak(1542, 28, 0.42),
            Peak(1452, 20, 0.14),
            Peak(1241, 25, 0.22),
            Peak(1078, 24, 0.34),
            Peak(970, 18, 0.13),
        ],
        baseline=0.018,
        slope=0.02,
        ripple=0.003,
    )
    write_spectrum_pair("protein_buffer_atr", "OMNIC synthetic protein buffer ATR", protein)

    unknown = spectrum(
        [
            Peak(3060, 24, 0.12),
            Peak(2960, 25, 0.19),
            Peak(1722, 22, 0.64),
            Peak(1601, 18, 0.24),
            Peak(1450, 18, 0.18),
            Peak(1244, 22, 0.42),
            Peak(1160, 18, 0.35),
            Peak(988, 17, 0.17),
            Peak(830, 15, 0.21),
        ],
        baseline=0.024,
        slope=0.016,
    )
    write_spectrum_pair("unknown_clear_coating", "OMNIC synthetic unknown clear coating", unknown)

    resin = spectrum(
        [
            Peak(2964, 24, 0.16),
            Peak(2872, 20, 0.10),
            Peak(1728, 20, 0.52),
            Peak(1510, 18, 0.18),
            Peak(1248, 20, 0.32),
            Peak(1115, 18, 0.28),
            Peak(915, 16, 0.24),
            Peak(760, 14, 0.16),
        ],
        baseline=0.022,
        slope=0.014,
    )
    write_spectrum_pair("resin_batch_qa", "OMNIC synthetic resin batch QA", resin)

    acrylic_ref = normalize(spectrum([Peak(1722, 20, 0.61), Peak(1600, 18, 0.22), Peak(1243, 22, 0.40), Peak(1162, 20, 0.34), Peak(830, 15, 0.20)], noise=0.0008))
    epoxy_ref = normalize(spectrum([Peak(3055, 23, 0.17), Peak(1608, 20, 0.33), Peak(1508, 18, 0.27), Peak(1248, 22, 0.22), Peak(915, 15, 0.42), Peak(830, 14, 0.14)], noise=0.0008))
    polyurethane_ref = normalize(spectrum([Peak(3330, 80, 0.25), Peak(2940, 25, 0.14), Peak(1728, 22, 0.45), Peak(1535, 24, 0.34), Peak(1220, 22, 0.25), Peak(1070, 20, 0.22)], noise=0.0008))
    write_csv(OUT / "reference_acrylic_coating.csv", "Reference acrylic coating", acrylic_ref)
    write_csv(OUT / "reference_epoxy_resin.csv", "Reference epoxy resin", epoxy_ref)
    write_csv(OUT / "reference_polyurethane.csv", "Reference polyurethane", polyurethane_ref)

    with (OUT / "README_COPY_TO_VM.md").open("w", encoding="utf-8") as handle:
        handle.write("# OMNIC Task Assets\n\n")
        handle.write("Copy the contents of this directory to the Windows VM so that these files exist under:\n\n")
        handle.write("`C:\\Users\\User\\OMNIC_data`\n\n")
        handle.write("The files are deterministic synthetic FTIR/ATR spectra for OSWorld OMNIC benchmark tasks. ")
        handle.write("They are not real experimental measurements. Each main spectrum has both `.jdx` and `.csv` forms; ")
        handle.write("use `.jdx` in OMNIC when possible and the companion `.csv` as an ASCII import fallback.\n")


def main() -> None:
    ensure_out()
    generate_assets()
    print(f"Wrote OMNIC task assets to {OUT}")


if __name__ == "__main__":
    main()

