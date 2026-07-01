# SciKit Task Assets

Copy or rename this `scikit_assets` directory so that the Windows VM contains:

`C:\Users\User\SciKit_data`

After copying, these paths must exist exactly:

- `C:\Users\User\SciKit_data\avantage`
- `C:\Users\User\SciKit_data\nanoscope`
- `C:\Users\User\SciKit_data\gms`

The files are deterministic synthetic XPS, AFM, and TEM/EELS examples. They are benchmark inputs, not real experimental measurements.

To keep the snapshot compact, NanoScope height-image tasks intentionally share `nanoscope\afm_multifeature_height.csv`, and GMS FFT/diffraction tasks intentionally share `gms\lattice_image.bmp`.
