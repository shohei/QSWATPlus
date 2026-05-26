# Suggested Commands

## Sync source to QGIS plugin
```bash
rsync -av \
  --include="*.py" --include="*.so" --include="*.qml" --include="*.qpt" \
  --include="*.sqlite" --include="*.png" --include="*.ico" --include="*.ui" \
  --include="*.pyi" --include="*.txt" --include="*.csv" --include="*.pyx" \
  --exclude="*.pyc" --exclude="__pycache__" --exclude="*.c" --exclude="build/" \
  --exclude="*.pyd" --exclude="*.pyd.old" --exclude="*.o" \
  --filter="-! */" \
  QSWATPlus/QSWATPlus/ \
  "~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/QSWATPlusMac3_64/QSWATPlus/"
```

## Compile Cython extensions (from QSWATPlus/QSWATPlus/)
See `mem:mac_setup` for the full compile command.

## QGIS Python interpreter
```bash
PYTHONHOME="/Applications/QGIS.app/Contents/Frameworks" \
/Applications/QGIS.app/Contents/MacOS/python3.12 script.py
```
