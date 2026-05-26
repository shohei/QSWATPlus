#!/usr/bin/env bash
# build_cython_mac.sh
# QSWATPlus の Cython 拡張モジュールを macOS (arm64) 向けにビルドする。
#
# 前提条件:
#   - QGIS 3.x が /Applications/QGIS.app または /Applications/QGIS-LTR.app にある
#   - Homebrew の python@3.12 がインストールされている (ヘッダファイル用)
#     brew install python@3.12
#
# 使い方:
#   ./build_cython_mac.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SRC="$REPO_ROOT/QSWATPlus"

# ---------------------------------------------------------------------------
# QGIS アプリの検出
# ---------------------------------------------------------------------------
if [[ -d "/Applications/QGIS-LTR.app" ]]; then
    QGIS_APP="/Applications/QGIS-LTR.app"
elif [[ -d "/Applications/QGIS.app" ]]; then
    QGIS_APP="/Applications/QGIS.app"
else
    echo "ERROR: QGIS が見つかりません (/Applications/QGIS.app または /Applications/QGIS-LTR.app)" >&2
    exit 1
fi

QGIS_PYTHON="$QGIS_APP/Contents/MacOS/python3.12"
PYTHONHOME="$QGIS_APP/Contents/Frameworks"

if [[ ! -x "$QGIS_PYTHON" ]]; then
    echo "ERROR: QGIS の python3.12 が見つかりません: $QGIS_PYTHON" >&2
    exit 1
fi

echo ">>> QGIS:   $QGIS_APP"
echo ">>> Python: $QGIS_PYTHON"

# ---------------------------------------------------------------------------
# Python 3.12 ヘッダファイルの検出 (Homebrew)
# ---------------------------------------------------------------------------
BREW_PY312_INCLUDE=""
for candidate in \
    /opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/include/python3.12 \
    /usr/local/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/include/python3.12
do
    if [[ -f "$candidate/Python.h" ]]; then
        BREW_PY312_INCLUDE="$candidate"
        break
    fi
done

if [[ -z "$BREW_PY312_INCLUDE" ]]; then
    echo "ERROR: Python 3.12 ヘッダが見つかりません。以下を実行してください:" >&2
    echo "  brew install python@3.12" >&2
    exit 1
fi

NUMPY_INCLUDE="$QGIS_APP/Contents/Frameworks/lib/python3.12/site-packages/numpy/core/include"
if [[ ! -d "$NUMPY_INCLUDE" ]]; then
    echo "ERROR: QGIS の numpy が見つかりません: $NUMPY_INCLUDE" >&2
    exit 1
fi

echo ">>> Python ヘッダ: $BREW_PY312_INCLUDE"
echo ">>> NumPy ヘッダ:  $NUMPY_INCLUDE"
echo ""

# ---------------------------------------------------------------------------
# UI ファイルのコンパイル (.ui → ui_*.py)
# ---------------------------------------------------------------------------
echo ">>> UI ファイルをコンパイルしています..."
PYTHONHOME="$PYTHONHOME" \
"$QGIS_PYTHON" - <<UIEOF
import sys, os
sys.path.insert(0, '$QGIS_APP/Contents/Resources/python')
sys.path.insert(0, '$QGIS_APP/Contents/Frameworks/lib/python3.12/site-packages')

from qgis.PyQt import uic

src_dir = '$PLUGIN_SRC'
os.chdir(src_dir)
ui_files = sorted(f for f in os.listdir(src_dir) if f.endswith('.ui'))
print(f'  {len(ui_files)} .ui files found')
for ui_file in ui_files:
    py_file = ui_file.replace('.ui', '.py')
    try:
        with open(os.path.join(src_dir, ui_file), 'r') as fi, \
             open(os.path.join(src_dir, py_file), 'w') as fo:
            uic.compileUi(fi, fo)
        print(f'  OK: {ui_file} -> {py_file}')
    except Exception as e:
        print(f'  FAIL: {ui_file}: {e}')
UIEOF

# PyQt uic が生成する "import resources_rc" は絶対インポートのため
# パッケージ内では失敗する。相対インポートに書き換える。
echo ">>> resources_rc インポートを相対インポートに修正..."
python3 - <<FIXEOF
import glob, os
src = '$PLUGIN_SRC'
fixed = 0
for path in sorted(glob.glob(f'{src}/ui_*.py')):
    data = open(path, 'rb').read()
    if b'import resources_rc' in data:
        open(path, 'wb').write(data.replace(b'import resources_rc', b'from . import resources_rc'))
        fixed += 1
print(f'  {fixed} files fixed')
FIXEOF

# ---------------------------------------------------------------------------
# コンパイル
# ---------------------------------------------------------------------------
cd "$PLUGIN_SRC"

PYTHONHOME="$PYTHONHOME" \
"$QGIS_PYTHON" - <<PYEOF
import sys, os
sys.argv = ['setup.py', 'build_ext', '--inplace']

from Cython.Build import cythonize
from setuptools import setup, Extension

include_dirs = [
    '$BREW_PY312_INCLUDE',
    '$NUMPY_INCLUDE',
]

modules = ['dataInC', 'jenks', 'polygonizeInC2']
extensions = []
for name in modules:
    pyx = name + '.pyx'
    if os.path.exists(pyx):
        extensions.append(Extension(
            name, [pyx],
            include_dirs=include_dirs,
            extra_compile_args=['-arch', 'arm64'],
            extra_link_args=['-arch', 'arm64'],
        ))
        print(f'  Found: {pyx}')
    else:
        print(f'  Skip (not found): {pyx}')

if not extensions:
    print('ERROR: コンパイルする .pyx ファイルがありません')
    sys.exit(1)

setup(ext_modules=cythonize(extensions, language_level=3))
PYEOF

# ---------------------------------------------------------------------------
# アドホック署名 (macOS 16+ では無署名 .so はロード不可。QGIS の
# disable-library-validation entitlement が Team ID 不一致を許可する)
# ---------------------------------------------------------------------------
echo ""
echo ">>> アドホック署名を適用しています..."
for so in "$PLUGIN_SRC"/*.cpython-312-darwin.so; do
    if [[ -f "$so" ]]; then
        codesign --force --sign - "$so"
        echo "  $(basename "$so")"
    fi
done

echo ""
echo "=== ビルド結果 ==="
for so in "$PLUGIN_SRC"/*.cpython-312-darwin.so; do
    [[ -f "$so" ]] && echo "  $(basename "$so")  [$(file "$so" | grep -oE 'arm64|x86_64|universal')]"
done
echo ""
echo ">>> 完了。次は package_mac.sh を実行して ZIP を作成してください。"
