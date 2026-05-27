#!/usr/bin/env bash
# install_python_deps_mac.sh
#
# QGIS の Python 環境に QSWATPlus の Visualize 機能で必要な
# matplotlib とその依存パッケージをインストールする。
#
# 使い方:
#   bash install_python_deps_mac.sh
#
# 前提:
#   - Homebrew の python@3.12 がインストール済みであること
#     (brew install python@3.12)

set -euo pipefail

# ---------------------------------------------------------------------------
# Python 3.12 の確認
# ---------------------------------------------------------------------------
PYTHON312="/opt/homebrew/bin/python3.12"
if [[ ! -x "$PYTHON312" ]]; then
    echo "ERROR: $PYTHON312 が見つかりません。" >&2
    echo "  brew install python@3.12 を実行してください。" >&2
    exit 1
fi
echo ">>> Python: $($PYTHON312 --version)"

# ---------------------------------------------------------------------------
# インストール先 (QGIS ユーザープロファイルの python ディレクトリ)
# ---------------------------------------------------------------------------
SITE_DIR="$HOME/Library/Application Support/QGIS/QGIS3/profiles/default/python"
if [[ ! -d "$SITE_DIR" ]]; then
    echo "ERROR: QGIS プロファイルディレクトリが見つかりません: $SITE_DIR" >&2
    echo "  QGIS を一度起動してからやり直してください。" >&2
    exit 1
fi
echo ">>> インストール先: $SITE_DIR"
echo ""

# ---------------------------------------------------------------------------
# 壊れた旧パッケージ (Python 3.14 版) の削除
# ---------------------------------------------------------------------------
echo ">>> 古いパッケージを削除中..."
for pkg in PIL matplotlib contourpy cycler fontTools dateutil kiwisolver; do
    if [[ -d "$SITE_DIR/$pkg" ]]; then
        rm -rf "${SITE_DIR:?}/$pkg"
        echo "    Removed: $pkg"
    fi
done
# .dist-info も削除
find "$SITE_DIR" -maxdepth 1 -name "*.dist-info" \
    | grep -iE "matplotlib|pillow|contourpy|cycler|fonttools|kiwisolver|python_dateutil" \
    | while read -r d; do rm -rf "$d"; echo "    Removed: $(basename "$d")"; done

# ---------------------------------------------------------------------------
# Python 3.12 版パッケージのインストール
# ---------------------------------------------------------------------------
echo ""
echo ">>> matplotlib と依存パッケージをインストール中..."

PKGS=(
    matplotlib
    pillow
    contourpy
    cycler
    fonttools
    kiwisolver
    pyparsing
    python-dateutil
    packaging
)

"$PYTHON312" -m pip install \
    "${PKGS[@]}" \
    --target "$SITE_DIR" \
    --upgrade \
    --no-deps \
    2>&1 | grep -v "^WARNING: Target directory.*already exists"

# ※ numpy は QGIS 内蔵版 (1.26.4) を使うため、あえてインストールしない

# ---------------------------------------------------------------------------
# 依存解決のために six も追加 (python-dateutil の依存)
# ---------------------------------------------------------------------------
"$PYTHON312" -m pip install six \
    --target "$SITE_DIR" \
    --upgrade \
    --no-deps \
    2>&1 | grep -v "^WARNING: Target directory.*already exists"

# ---------------------------------------------------------------------------
# 動作確認
# ---------------------------------------------------------------------------
QGIS_SITE="/Applications/QGIS.app/Contents/Frameworks/lib/python3.12/site-packages"
echo ""
echo ">>> インポート確認..."

"$PYTHON312" -c "
import sys
sys.path.insert(0, '$SITE_DIR')
sys.path.append('$QGIS_SITE')

errors = []

for mod, label in [
    ('matplotlib',                                  'matplotlib'),
    ('mpl_toolkits.axes_grid1.axes_divider',        'axes_grid1'),
    ('contourpy',                                   'contourpy'),
    ('PIL',                                         'Pillow'),
]:
    try:
        __import__(mod)
        print('  OK:', label)
    except Exception as e:
        errors.append((label, str(e)))
        print('  NG:', label, '->', e)

if errors:
    print()
    print('ERROR: 一部のインポートが失敗しました。上記を確認してください。')
    sys.exit(1)
else:
    print()
    print('=== すべてのパッケージが正常にインポートできました ===')
" 2>&1

echo ""
echo "QGIS を再起動すると Visualize ボタンが使えるようになります。"
