# Task Completion

After making code changes to QSWATPlus:

1. **Sync to plugin directory** (see `mem:suggested_commands`)
2. **If .pyx files changed**: recompile Cython extensions (see `mem:mac_setup`)
3. **If .ui files changed**: recompile with `qgis.PyQt.uic.compileUi` (see `mem:mac_setup`)
4. **Reload plugin in QGIS**: Plugin Manager → Reload, or restart QGIS

No formal test suite to run (test files exist but require QGIS environment).
