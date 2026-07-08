# SciKit and OMNIC Task Assets

The Windows task configs upload the required local asset files during setup.
Manual pre-copying of the whole directory into the VM is no longer required for
the JSON tasks when they are run from the repository root.

Each task copies only the files it needs directly into:

- `C:\Users\User`

Task instructions also ask agents to save exported results in the same directory.
The local asset folders remain organized by application:

- `avantage` contains externally sourced CasaXPS VAMAS XPS inputs.
- `nanoscope` and `gms` contain deterministic synthetic AFM and TEM/EELS
  benchmark inputs.
- `omnic` contains deterministic synthetic FTIR/ATR benchmark inputs.

NanoScope height-image tasks intentionally share
`nanoscope\afm_multifeature_height.csv`, GMS FFT/diffraction tasks share
`gms\lattice_image.bmp`, and most OMNIC tasks share
`omnic\unknown_clear_coating.jdx`. The OMNIC library-match task also uploads
`omnic\coating_reference_library.csv`.
