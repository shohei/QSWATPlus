# QSWATPlus Project Core

QSWATPlus is a QGIS plugin for creating SWAT+ (Soil and Water Assessment Tool) watershed model inputs.

## Project Structure
- `QSWATPlus/` — main plugin source code (Python)
- `QSWATPlus/QSWATPlus/` — the actual plugin module
- Plugin is installed at `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/QSWATPlusMac3_64/`

## Key Source Files
- `parameters.py` — platform detection, default paths (SWATPlus, TauDEM, QGIS)
- `TauDEMUtils.py` — TauDEM binary execution (watershed delineation)
- `globals.py` — global variables and project state
- `QSWATPlusMain.py` — plugin entry point
- `dataInC.pyx`, `jenks.pyx`, `polygonizeInC2.pyx` — Cython extensions (must be compiled)

## Related Memories
- `mem:tech_stack` — language, QGIS version, Python version
- `mem:mac_setup` — Mac-specific setup steps and issues
- `mem:conventions` — code conventions
