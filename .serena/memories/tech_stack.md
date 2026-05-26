# Tech Stack

- Language: Python 3.12 (inside QGIS)
- QGIS: 3.44.6-Solothurn at `/Applications/QGIS.app` (universal binary: arm64 + x86_64)
- QGIS Python: `/Applications/QGIS.app/Contents/MacOS/python3.12` (Python 3.12.11)
- QGIS Python env: `PYTHONHOME=/Applications/QGIS.app/Contents/Frameworks`
- PyQt: 5.15.10 via `qgis.PyQt` (no standalone PyQt5/PyQt6)
- Cython: 3.2.2 (included in QGIS Python site-packages)
- NumPy: 1.26.4 (included in QGIS Python site-packages)
- SWATPlus dir: `~/SWATPlus/` (Databases, TauDEM5Bin, SWATPlusEditor, etc.)
- TauDEM: `~/SWATPlus/TauDEM5Bin/` (arm64 native binaries)
- GDAL: QGIS bundles libgdal.38 (GDAL 3.12.0) in Contents/Frameworks
- MPI: Open MPI at `/opt/homebrew/opt/open-mpi/` (libmpi.40.dylib)
