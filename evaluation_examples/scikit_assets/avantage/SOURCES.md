# Avantage XPS sample source

The Avantage tasks use one externally sourced VAMAS XPS file:

- Local file: `quant_by_xps.vms`
- Source package: CasaXPS Video Channel, `Quantification by XPS: An Overview`
- Download URL: https://www.casa-software.com/index.php?zipfile=VVhWaGJuUkNlVmhRVXk1NmFYQT1NREF3TURBd1FYTndaV04wYzA5bQ%3D%3D
- View URL: https://www.casa-software.com/index.php?vmsblock=0&vmsfile=VVhWaGJuUkNlVmhRVXk1MmJYTT1NREF3TURBd1FYTndaV04wYzA5bQ%3D%3D&vmsregion=-1
- Zip member extracted: `AspectsOfQuantByXPS/EscapeDepth-MgFoil-pkmdl-Mg1s-Mg2s.vms`

The file is VAMAS (`.vms`), not Thermo Avantage native `.vgp`. It is used because
publicly downloadable native `.vgp` examples were not found, while Avantage can
import compatible XPS data formats. If a native Avantage project is needed later,
open/import `quant_by_xps.vms` in Avantage and save/export it as `.vgp`.

Temporary download archives such as `QuantByXPS.zip` should not be committed.
