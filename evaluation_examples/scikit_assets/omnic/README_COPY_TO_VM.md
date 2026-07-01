# OMNIC Task Assets

The OMNIC Windows task configs upload the required files from this directory to
`C:\Users\User` during setup when run from the repository root.

Task instructions also ask agents to save exported results in the same directory.
These deterministic synthetic FTIR/ATR spectra are benchmark inputs, not real
experimental measurements. All OMNIC tasks use `unknown_clear_coating.jdx`; the
library-match task also uses `coating_reference_library.csv`.
