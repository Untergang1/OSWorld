# Avantage XPS sample source

The Avantage tasks use one compressed native Avantage project package:

- Task asset: `quant_by_xps.zip`
- VM upload path used by tasks: `C:\Users\User\quant_by_xps.zip`
- VM project path after setup extraction: `C:\Users\User\quant_by_xps.vgp`
- VM data directory after setup extraction: `C:\Users\User\quant_by_xps.DATA\`
- Exported by the user from Avantage after importing the upstream VAMAS file below.

Upstream data provenance:

- Upstream VAMAS file kept in this directory: `quant_by_xps.vms`
- Source package: CasaXPS Video Channel, `Quantification by XPS: An Overview`
- Download URL: https://www.casa-software.com/index.php?zipfile=VVhWaGJuUkNlVmhRVXk1NmFYQT1NREF3TURBd1FYTndaV04wYzA5bQ%3D%3D
- View URL: https://www.casa-software.com/index.php?vmsblock=0&vmsfile=VVhWaGJuUkNlVmhRVXk1MmJYTT1NREF3TURBd1FYTndaV04wYzA5bQ%3D%3D&vmsregion=-1
- Zip member extracted: `AspectsOfQuantByXPS/EscapeDepth-MgFoil-pkmdl-Mg1s-Mg2s.vms`

The `quant_by_xps.zip` runtime asset contains `quant_by_xps.vgp` and the
associated `quant_by_xps.DATA` folder required by Avantage. The `.vms` file
remains as the public upstream data source and provenance record. Temporary
download archives such as `QuantByXPS.zip` should not be committed.
