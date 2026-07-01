r"""Generate minimal deterministic FTIR assets for Windows OMNIC tasks.

Copy the generated files to a Windows VM snapshot at C:\Users\User\OMNIC_data.
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


def write_reference_library(
    path: Path,
    acrylic: Sequence[tuple[float, float]],
    epoxy: Sequence[tuple[float, float]],
    polyurethane: Sequence[tuple[float, float]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["wavenumber_cm-1", "acrylic_absorbance", "epoxy_absorbance", "polyurethane_absorbance"])
        for (wn, acrylic_y), (_, epoxy_y), (_, polyurethane_y) in zip(acrylic, epoxy, polyurethane):
            writer.writerow([f"{wn:.2f}", f"{acrylic_y:.6f}", f"{epoxy_y:.6f}", f"{polyurethane_y:.6f}"])


def generate_assets() -> None:
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
    write_jdx(OUT / "unknown_clear_coating.jdx", "OMNIC synthetic unknown clear coating", unknown)

    acrylic_ref = normalize(
        spectrum(
            [Peak(1722, 20, 0.61), Peak(1600, 18, 0.22), Peak(1243, 22, 0.40), Peak(1162, 20, 0.34), Peak(830, 15, 0.20)],
            noise=0.0008,
        )
    )
    epoxy_ref = normalize(
        spectrum(
            [Peak(3055, 23, 0.17), Peak(1608, 20, 0.33), Peak(1508, 18, 0.27), Peak(1248, 22, 0.22), Peak(915, 15, 0.42), Peak(830, 14, 0.14)],
            noise=0.0008,
        )
    )
    polyurethane_ref = normalize(
        spectrum(
            [Peak(3330, 80, 0.25), Peak(2940, 25, 0.14), Peak(1728, 22, 0.45), Peak(1535, 24, 0.34), Peak(1220, 22, 0.25), Peak(1070, 20, 0.22)],
            noise=0.0008,
        )
    )
    write_reference_library(OUT / "coating_reference_library.csv", acrylic_ref, epoxy_ref, polyurethane_ref)

    with (OUT / "README_COPY_TO_VM.md").open("w", encoding="utf-8") as handle:
        handle.write("# OMNIC Task Assets\n\n")
        handle.write("Copy the contents of this directory to the Windows VM so these files exist under:\n\n")
        handle.write("`C:\\Users\\User\\OMNIC_data`\n\n")
        handle.write("These deterministic synthetic FTIR/ATR spectra are benchmark inputs, not real experimental measurements. ")
        handle.write("All OMNIC tasks use `unknown_clear_coating.jdx`; the library-match task also uses `coating_reference_library.csv`.\n")


def main() -> None:
    ensure_out()
    generate_assets()
    print(f"Wrote OMNIC task assets to {OUT}")


if __name__ == "__main__":
    main()
