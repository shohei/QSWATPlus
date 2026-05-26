# Code Conventions

- Platform detection via `Parameters._ISWIN`, `Parameters._ISLINUX`, `Parameters._ISMAC`
- Path joining uses `QSWATUtils.join()` not `os.path.join()` for cross-platform
- UI dialogs: `.ui` files compiled to `ui_*.py` via `qgis.PyQt.uic.compileUi`
- Import style: relative imports (`.module`) inside plugin package, absolute inside tests
- Type hints used throughout (Python 3.x style)
- `# type: ignore` and `# @UnresolvedImport` used for Cython imports
- No docstrings for most methods; triple-quoted only on classes and important functions
