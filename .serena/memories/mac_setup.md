# Mac Setup for QSWATPlus

## QGIS Installation
- QGIS 3.44 at `/Applications/QGIS.app` (not QGIS-LTR.app)
- Plugin installed at: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/QSWATPlusMac3_64/`

## Code Fixes Applied
1. **`parameters.py`**: `_MACQGISDIR` now auto-detects: falls back to `/Applications/QGIS.app` if QGIS-LTR.app not found
2. **`parameters.py`**: `_SVGDIR` uses `_MACQGISDIR` variable (not hardcoded)
3. **`TauDEMUtils.py`**: `MacPrefix` path fixed: `Contents/Frameworks` (not `Contents/MacOS/lib`) and `Contents/Resources/qgis/proj` (not `Contents/Resources/proj`)

## Cython Extension Compilation (Python 3.12 arm64)
Compile `dataInC.pyx`, `jenks.pyx`, `polygonizeInC2.pyx`:
```bash
cd QSWATPlus/QSWATPlus
PYTHON312_INCLUDE="/opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/include/python3.12"
NUMPY_INCLUDE="/Applications/QGIS.app/Contents/Frameworks/lib/python3.12/site-packages/numpy/core/include"
PYTHONHOME="/Applications/QGIS.app/Contents/Frameworks" \
/Applications/QGIS.app/Contents/MacOS/python3.12 -c "
import sys, os; sys.argv=['setup.py','build_ext','--inplace']
from Cython.Build import cythonize; from setuptools import setup, Extension; import numpy
extensions = [Extension(n, [n+'.pyx'], include_dirs=['$PYTHON312_INCLUDE','$NUMPY_INCLUDE'],
    extra_compile_args=['-arch','arm64'], extra_link_args=['-arch','arm64'])
    for n in ['dataInC','jenks','polygonizeInC2'] if os.path.exists(n+'.pyx')]
setup(ext_modules=cythonize(extensions, language_level=3))
"
```
- Do NOT sign the .so files (QGIS has `disable-library-validation` entitlement so unsigned .so loads fine)
- Compiled .so files must NOT have ad-hoc signatures (causes Team ID mismatch errors when tested via CLI, but QGIS loads them fine unsigned)

## TauDEM Library Fix
TauDEM binaries need `libgdal.33.dylib` but only gdal.39 (Homebrew) or gdal.38 (QGIS) are installed:
```bash
ln -sf /Applications/QGIS.app/Contents/Frameworks/libgdal.38.dylib /opt/homebrew/opt/gdal/lib/libgdal.33.dylib
```
- QGIS's libgdal.38 uses `@loader_path` RPATH so its dependencies resolve from QGIS Frameworks
- MPI: Open MPI at `/opt/homebrew/opt/open-mpi/` provides `libmpi.40.dylib` ✅

## Plugin Sync Script
After code changes:
```bash
rsync -av --include="*.py" --include="*.so" --include="*.qml" ... \
  QSWATPlus/QSWATPlus/ \
  ~/Library/.../QSWATPlusMac3_64/QSWATPlus/
```

## UI File Compilation
```bash
PYTHONHOME="/Applications/QGIS.app/Contents/Frameworks" \
/Applications/QGIS.app/Contents/MacOS/python3.12 -c "
from qgis.PyQt.uic import compileUi
with open('ui_X.ui') as fin, open('ui_X.py','w') as fout:
    compileUi(fin, fout)
"
```
