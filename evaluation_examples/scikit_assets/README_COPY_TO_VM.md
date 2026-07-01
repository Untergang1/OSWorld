# SciKit and OMNIC Task Assets

The Windows task configs upload the required local asset files during setup.
Manual pre-copying of the whole directory into the VM is no longer required for
the JSON tasks when they are run from the repository root.

The setup steps copy only the files needed by the current task into these VM
locations:

- `C:\Users\User\SciKit_data\avantage`
- `C:\Users\User\SciKit_data\nanoscope`
- `C:\Users\User\SciKit_data\gms`
- `C:\Users\User\OMNIC_data`

Local asset folders map to those VM locations as follows:

- `avantage`, `nanoscope`, and `gms` contain deterministic synthetic XPS, AFM,
  and TEM/EELS benchmark inputs.
- `omnic` contains deterministic synthetic FTIR/ATR benchmark inputs.

NanoScope height-image tasks intentionally share
`nanoscope\afm_multifeature_height.csv`, GMS FFT/diffraction tasks share
`gms\lattice_image.bmp`, and most OMNIC tasks share
`omnic\unknown_clear_coating.jdx`. The OMNIC library-match task also uploads
`omnic\coating_reference_library.csv`.
