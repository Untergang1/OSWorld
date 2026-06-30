r"""Generate deterministic synthetic data for the SciKit Windows tasks.

The files are intentionally small and self-contained so they can be copied to a
Windows VM snapshot at C:\Users\User\SciKit_data.
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
    if OUT.exists():
        for path in sorted(OUT.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
    for name in ("avantage", "nanoscope", "gms"):
        (OUT / name).mkdir(parents=True, exist_ok=True)


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


def write_vms_like(path: Path, title: str, x_label: str, y_label: str, rows: np.ndarray) -> None:
    """Write a compact VAMAS-style ASCII transfer file plus tabular data.

    Avantage installations usually understand VAMAS/ASCII imports, but exact
    vendor binary formats are not generated here. The table is deliberately
    transparent so the same file remains usable through text/ASCII import.
    """

    with path.open("w", newline="", encoding="utf-8") as handle:
        handle.write("VAMAS Surface Chemical Analysis Standard Data Transfer Format\n")
        handle.write(f"Experiment: {title}\n")
        handle.write("Technique: XPS\n")
        handle.write(f"Columns: {x_label}, {y_label}\n")
        handle.write("DataStart\n")
        writer = csv.writer(handle)
        writer.writerow([x_label, y_label])
        writer.writerows(rows)


def generate_avantage() -> None:
    base = OUT / "avantage"

    be = np.linspace(0, 1200, 1201)
    counts = (
        1200
        + 45 * np.sqrt(be + 1)
        + gaussian(be, 284.8, 1.4, 22000)
        + gaussian(be, 399.8, 1.8, 3600)
        + gaussian(be, 532.0, 2.1, 8800)
        + gaussian(be, 103.3, 1.5, 4400)
        + RNG.normal(0, 45, be.size)
    )
    survey_rows = np.column_stack([be, np.maximum(counts, 0)])
    write_vms_like(base / "polymer_survey.vms", "Polymer film survey", "binding_energy_eV", "counts", survey_rows)
    write_xy_csv(base / "polymer_survey.csv", ["binding_energy_eV", "counts"], survey_rows)

    c1s_be = np.linspace(278, 294, 641)
    c1s = (
        220
        + gaussian(c1s_be, 284.8, 0.55, 9300)
        + gaussian(c1s_be, 286.4, 0.75, 4100)
        + gaussian(c1s_be, 288.7, 0.9, 1300)
        + 25 * (294 - c1s_be)
        + RNG.normal(0, 25, c1s_be.size)
    )
    write_vms_like(base / "polymer_c1s_region.vms", "Polymer film C 1s high resolution", "binding_energy_eV", "counts", np.column_stack([c1s_be, c1s]))

    tio2_be = np.linspace(280, 540, 1041)
    tio2 = (
        500
        + gaussian(tio2_be, 284.8, 0.8, 2500)
        + gaussian(tio2_be, 458.7, 0.9, 12000)
        + gaussian(tio2_be, 464.4, 1.1, 6200)
        + gaussian(tio2_be, 529.9, 1.0, 14500)
        + gaussian(tio2_be, 531.7, 1.3, 3200)
        + RNG.normal(0, 30, tio2_be.size)
    )
    write_vms_like(base / "tio2_regions.vms", "TiO2 reference regions", "binding_energy_eV", "counts", np.column_stack([tio2_be, tio2]))

    times = np.array([0, 2, 5, 10, 15, 20, 30, 45, 60], dtype=float)
    al = 8 + 67 * (1 - np.exp(-times / 18))
    oxygen = 48 - 17 * (1 - np.exp(-times / 20))
    carbon = 34 * np.exp(-times / 8)
    silicon = 100 - al - oxygen - carbon
    depth_rows = np.column_stack([times, al, oxygen, carbon, silicon])
    write_xy_csv(
        base / "al_oxide_depth_profile.csv",
        ["sputter_time_s", "Al_atomic_percent", "O_atomic_percent", "C_atomic_percent", "Si_atomic_percent"],
        depth_rows,
    )

    yy, xx = np.mgrid[-1:1:96j, -1:1:96j]
    oxygen_map = 0.35 + 0.45 * np.exp(-((xx + 0.25) ** 2 + (yy - 0.15) ** 2) / 0.18) + 0.05 * RNG.random((96, 96))
    silicon_map = 0.35 + 0.4 * np.exp(-((xx - 0.35) ** 2 + (yy + 0.15) ** 2) / 0.20) + 0.04 * RNG.random((96, 96))
    carbon_map = 0.18 + 0.15 * RNG.random((96, 96))
    write_matrix_csv(base / "oxide_o1s_map.csv", oxygen_map * 100, 0.25, "O1s_atomic_percent")


def generate_nanoscope() -> None:
    base = OUT / "nanoscope"
    size = 128
    y, x = np.mgrid[0:size, 0:size]
    pixel_nm = 4.0

    terrace = 25 * (x > 58) + 0.12 * x + 0.08 * y + 1.5 * np.sin(y / 8) + RNG.normal(0, 0.45, (size, size))
    write_matrix_csv(base / "tilted_polymer_terrace.csv", terrace, pixel_nm, "height_nm")
    save_grayscale_bmp(base / "tilted_polymer_terrace.bmp", terrace)

    rough = 2.5 * RNG.normal(0, 1, (size, size)) + 1.2 * np.sin(x / 6)
    rough[55:68, 12:118] -= 18
    write_matrix_csv(base / "roughness_scratch_height.csv", rough, pixel_nm, "height_nm")
    save_grayscale_bmp(base / "roughness_scratch_height.bmp", rough)

    step = 1.2 * RNG.normal(0, 1, (size, size)) + 42 * (x > 64) + 4 * np.sin(x / 18)
    write_matrix_csv(base / "step_grating_height.csv", step, pixel_nm, "height_nm")
    save_grayscale_bmp(base / "step_grating_height.bmp", step)

    particles = RNG.normal(0, 0.7, (size, size))
    centers = [(24, 31, 9), (45, 84, 7), (72, 42, 12), (92, 96, 8), (108, 58, 10), (34, 108, 6), (82, 18, 7)]
    for cy, cx, amp in centers:
        particles += amp * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * 4.2**2))
    write_matrix_csv(base / "nanoparticles_height.csv", particles, pixel_nm, "height_nm")
    save_grayscale_bmp(base / "nanoparticles_height.bmp", particles)

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

    r = np.sqrt((x - 128) ** 2 + (y - 128) ** 2)
    saed = (
        gaussian(r, 0, 2.2, 4.0)
        + gaussian(r, 38, 1.8, 1.2)
        + gaussian(r, 66, 2.2, 1.0)
        + gaussian(r, 94, 2.6, 0.75)
        + 0.08 * RNG.random((size, size))
    )
    save_grayscale_bmp(base / "saed_pattern.bmp", saed)


def write_readme() -> None:
    (OUT / "README_COPY_TO_VM.md").write_text(
        "# SciKit Task Assets\n\n"
        "Copy or rename this `scikit_assets` directory so that the Windows VM contains:\n\n"
        "`C:\\Users\\User\\SciKit_data`\n\n"
        "After copying, these paths must exist exactly:\n\n"
        "- `C:\\Users\\User\\SciKit_data\\avantage`\n"
        "- `C:\\Users\\User\\SciKit_data\\nanoscope`\n"
        "- `C:\\Users\\User\\SciKit_data\\gms`\n\n"
        "The files are deterministic synthetic XPS, AFM, and TEM/EELS examples. "
        "They are benchmark inputs, not real experimental measurements.\n",
        encoding="utf-8",
    )


def main() -> None:
    ensure_dirs()
    generate_avantage()
    generate_nanoscope()
    generate_gms()
    write_readme()
    print(f"Wrote assets to {OUT}")


if __name__ == "__main__":
    main()

