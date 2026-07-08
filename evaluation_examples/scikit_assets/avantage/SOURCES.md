# Avantage XPS sample source

The Avantage tasks use one native Avantage project file:

- Task asset: `quant_by_xps.vgp`
- VM path used by tasks: `C:\Users\User\quant_by_xps.vgp`
- Exported by the user from Avantage after importing the upstream VAMAS file below.

Upstream data provenance:

- Upstream VAMAS file kept in this directory: `quant_by_xps.vms`
- Source package: CasaXPS Video Channel, `Quantification by XPS: An Overview`
- Download URL: https://www.casa-software.com/index.php?zipfile=VVhWaGJuUkNlVmhRVXk1NmFYQT1NREF3TURBd1FYTndaV04wYzA5bQ%3D%3D
- View URL: https://www.casa-software.com/index.php?vmsblock=0&vmsfile=VVhWaGJuUkNlVmhRVXk1MmJYTT1NREF3TURBd1FYTndaV04wYzA5bQ%3D%3D&vmsregion=-1
- Zip member extracted: `AspectsOfQuantByXPS/EscapeDepth-MgFoil-pkmdl-Mg1s-Mg2s.vms`

The `.vgp` file is the runtime asset for Avantage tasks because it is a native
Avantage project. The `.vms` file remains as the public upstream data source and
provenance record. Temporary download archives such as `QuantByXPS.zip` should
not be committed.
