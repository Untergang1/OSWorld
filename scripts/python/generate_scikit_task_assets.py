r"""Generate deterministic synthetic data for the SciKit Windows tasks.

The files are intentionally small and self-contained. Windows task configs
upload each required asset from evaluation_examples/scikit_assets during setup.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evaluation_examples" / "scikit_assets"
RNG = np.random.default_rng(20260630)


def gaussian(x: np.ndarray, center: float, width: float, amplitude: float) -> np.ndarray:
    return amplitude * np.exp(-0.5 * ((x - center) / width) ** 2)


def ensure_dirs() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "avantage").mkdir(parents=True, exist_ok=True)
    for name in ("nanoscope", "gms"):
        target = OUT / name
        if target.exists():
            for path in sorted(target.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
        target.mkdir(parents=True, exist_ok=True)


def write_xy_csv(path: Path, header: list[str], rows: np.ndarray) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def write_matrix_csv(path: Path, matrix: np.ndarray, pixel_nm: float, channel: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x_nm", "y_nm", channel])
        height, width = matrix.shape
        for row in range(height):
            for col in range(width):
                writer.writerow([f"{col * pixel_nm:.4f}", f"{row * pixel_nm:.4f}", f"{matrix[row, col]:.6f}"])


def _write_bmp(path: Path, rgb: np.ndarray) -> None:
    """Write an uncompressed 24-bit BMP without external image libraries."""
    height, width, channels = rgb.shape
    if channels != 3:
        raise ValueError("BMP writer expects RGB data")
    row_stride = (width * 3 + 3) // 4 * 4
    image_size = row_stride * height
    file_size = 54 + image_size

    with path.open("wb") as handle:
        handle.write(b"BM")
        handle.write(file_size.to_bytes(4, "little"))
        handle.write((0).to_bytes(4, "little"))
        handle.write((54).to_bytes(4, "little"))
        handle.write((40).to_bytes(4, "little"))
        handle.write(width.to_bytes(4, "little", signed=True))
        handle.write(height.to_bytes(4, "little", signed=True))
        handle.write((1).to_bytes(2, "little"))
        handle.write((24).to_bytes(2, "little"))
        handle.write((0).to_bytes(4, "little"))
        handle.write(image_size.to_bytes(4, "little"))
        handle.write((2835).to_bytes(4, "little", signed=True))
        handle.write((2835).to_bytes(4, "little", signed=True))
        handle.write((0).to_bytes(4, "little"))
        handle.write((0).to_bytes(4, "little"))

        pad = b"\x00" * (row_stride - width * 3)
        for row in range(height - 1, -1, -1):
            bgr = rgb[row, :, ::-1].astype(np.uint8).tobytes()
            handle.write(bgr + pad)


def save_grayscale_bmp(path: Path, data: np.ndarray) -> None:
    clipped = np.asarray(data, dtype=float)
    clipped = clipped - clipped.min()
    if clipped.max() > 0:
        clipped = clipped / clipped.max()
    channel = np.uint8(clipped * 255)
    _write_bmp(path, np.dstack([channel, channel, channel]))


def save_rgb_bmp(path: Path, channels: list[np.ndarray]) -> None:
    rgb = []
    for channel in channels:
        ch = np.asarray(channel, dtype=float)
        ch = ch - ch.min()
        if ch.max() > 0:
            ch = ch / ch.max()
        rgb.append(np.uint8(ch * 255))
    _write_bmp(path, np.dstack(rgb))



def generate_nanoscope() -> None:
    base = OUT / "nanoscope"
    size = 128
    y, x = np.mgrid[0:size, 0:size]
    pixel_nm = 4.0

    height = (
        0.12 * x
        + 0.08 * y
        + 1.5 * np.sin(y / 8)
        + 42 * (x > 64)
        + 2.0 * RNG.normal(0, 1, (size, size))
    )
    height[55:68, 12:118] -= 18
    centers = [(24, 31, 9), (45, 84, 7), (72, 42, 12), (92, 96, 8), (108, 58, 10), (34, 108, 6), (82, 18, 7)]
    for cy, cx, amp in centers:
        height += amp * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * 4.2**2))
    write_matrix_csv(base / "afm_multifeature_height.csv", height, pixel_nm, "height_nm")

    # Preserve downstream deterministic files after consolidating four height maps into one.
    for _ in range(3):
        RNG.normal(0, 1, (size, size))

    distance = np.linspace(-120, 120, 481)
    force = 0.015 * distance + 6 / (1 + np.exp(-(distance - 20) / 7)) - 2.5 * np.exp(-((distance + 22) / 16) ** 2)
    force += RNG.normal(0, 0.08, distance.size)
    write_xy_csv(base / "adhesion_force_curve.csv", ["z_distance_nm", "force_nN"], np.column_stack([distance, force]))


def generate_gms() -> None:
    base = OUT / "gms"
    size = 256
    y, x = np.mgrid[0:size, 0:size]

    lattice = (
        0.55
        + 0.22 * np.sin(2 * math.pi * x / 18.0)
        + 0.18 * np.sin(2 * math.pi * (0.55 * x + 0.83 * y) / 18.5)
        + 0.12 * np.sin(2 * math.pi * y / 31.0)
        + 0.08 * RNG.normal(0, 1, (size, size))
    )
    aperture = np.exp(-(((x - 128) ** 2 + (y - 128) ** 2) / (2 * 105**2)))
    lattice = lattice * aperture
    save_grayscale_bmp(base / "lattice_image.bmp", lattice)

    energy = np.linspace(200, 650, 901)
    background = 5500 * (energy / 200) ** -1.55
    eels = background + 1200 * (1 - np.exp(-(energy - 284) / 18)) * (energy > 284)
    eels += 1750 * (1 - np.exp(-(energy - 532) / 22)) * (energy > 532)
    eels += gaussian(energy, 292, 4.5, 900) + gaussian(energy, 540, 6.5, 800) + RNG.normal(0, 18, energy.size)
    write_xy_csv(base / "eels_core_loss_spectrum.csv", ["energy_loss_eV", "intensity_counts"], np.column_stack([energy, eels]))

    yy, xx = np.mgrid[-1:1:128j, -1:1:128j]
    c_map = np.exp(-((xx + 0.35) ** 2 + (yy + 0.05) ** 2) / 0.28) + 0.06 * RNG.random((128, 128))
    o_map = np.exp(-((xx - 0.25) ** 2 + (yy - 0.15) ** 2) / 0.22) + 0.06 * RNG.random((128, 128))
    si_map = np.exp(-((xx + 0.05) ** 2 + (yy - 0.35) ** 2) / 0.18) + 0.05 * RNG.random((128, 128))
    save_grayscale_bmp(base / "eels_spectrum_image.bmp", c_map + o_map + si_map)


def write_readme() -> None:
    (OUT / "README_COPY_TO_VM.md").write_text(
        "# SciKit and OMNIC Task Assets\n\n"
        "The Windows task configs upload the required local asset files during setup.\n"
        "Manual pre-copying of the whole directory into the VM is no longer required for\n"
        "the JSON tasks when they are run from the repository root.\n\n"
        "Each task copies only the files it needs directly into:\n\n"
        "- `C:\\Users\\User`\n\n"
        "Task instructions also ask agents to save exported results in the same directory.\n"
        "The local asset folders remain organized by application:\n\n"
        "- `avantage`, `nanoscope`, and `gms` contain deterministic synthetic XPS, AFM,\n"
        "  and TEM/EELS benchmark inputs.\n"
        "- `omnic` contains deterministic synthetic FTIR/ATR benchmark inputs.\n\n"
        "NanoScope height-image tasks intentionally share\n"
        "`nanoscope\\afm_multifeature_height.csv`, GMS FFT/diffraction tasks share\n"
        "`gms\\lattice_image.bmp`, and most OMNIC tasks share\n"
        "`omnic\\unknown_clear_coating.jdx`. The OMNIC library-match task also uploads\n"
        "`omnic\\coating_reference_library.csv`.\n",
        encoding="utf-8",
    )


def main() -> None:
    ensure_dirs()
    generate_nanoscope()
    generate_gms()
    write_readme()
    print(f"Wrote assets to {OUT}")


if __name__ == "__main__":
    main()

