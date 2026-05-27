#!/usr/bin/env bash
# package_mac.sh
# QSWATPlus Mac プラグインを QGIS にインストール可能な .zip に固める。
#
# 使い方:
#   ./package_mac.sh [--install] [出力先ディレクトリ]
#
#   --install   ZIP 作成後、QGIS プラグインディレクトリに直接展開してインストールする
#
# 出力先を省略した場合はリポジトリルートに出力する。
# .so (Cython 拡張) が未コンパイルの場合は終了コード 1 で中断する。
#
# 前提条件:
#   1. Cython 拡張をあらかじめビルドしておく (build_cython_mac.sh を参照)
#   2. macOS 上で実行すること

set -euo pipefail

# ---------------------------------------------------------------------------
# 引数解析
# ---------------------------------------------------------------------------
DO_INSTALL=0
OUTPUT_ARG=""
for arg in "$@"; do
    if [[ "$arg" == "--install" ]]; then
        DO_INSTALL=1
    else
        OUTPUT_ARG="$arg"
    fi
done

# ---------------------------------------------------------------------------
# パス定義
# ---------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SRC="$REPO_ROOT/QSWATPlus"          # プラグイン本体ソース
PLUGIN_NAME="QSWATPlusMac3_64"

# バージョンを QSWATPlusMain.py から読み取る
VERSION=$(grep "__version__" "$PLUGIN_SRC/QSWATPlusMain.py" \
          | head -1 | grep -oE "[0-9]+\.[0-9]+\.[0-9]+")

OUTPUT_DIR="${OUTPUT_ARG:-$REPO_ROOT}"
OUTPUT_ZIP="$OUTPUT_DIR/${PLUGIN_NAME}_${VERSION}.zip"

# QGIS プラグインインストール先 (QGIS デフォルトプロファイル)
QGIS_PLUGIN_DIR="$HOME/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins"

# ---------------------------------------------------------------------------
# 前提チェック
# ---------------------------------------------------------------------------
MISSING_SO=0
for module in dataInC jenks polygonizeInC2; do
    so="$PLUGIN_SRC/${module}.cpython-312-darwin.so"
    if [[ ! -f "$so" ]]; then
        echo "ERROR: 未コンパイル: $so" >&2
        MISSING_SO=1
    fi
done
if [[ $MISSING_SO -eq 1 ]]; then
    echo ""
    echo "Cython 拡張が見つかりません。先に build_cython_mac.sh を実行してください。" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 一時ディレクトリで組み立て
# ---------------------------------------------------------------------------
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

DEST="$WORK/$PLUGIN_NAME"
mkdir -p "$DEST/QSWATPlus"

echo ">>> バージョン: $VERSION"
echo ">>> 出力先:     $OUTPUT_ZIP"
echo ""

# ---------------------------------------------------------------------------
# ルートレベル (QSWATPlusMac3_64/ 直下)
# ---------------------------------------------------------------------------

# QGIS プラグインエントリポイント
cp "$PLUGIN_SRC/__init__.py" "$DEST/__init__.py"

# Mac 用 metadata (バージョンを最新に書き換えて配置)
sed "s/^version=.*/version=$VERSION/" \
    "$PLUGIN_SRC/metadatamac3_64.txt" > "$DEST/metadata.txt"

# HUC バッチ実行スクリプト (リポジトリルートにある)
if [[ -f "$REPO_ROOT/runHUC.py" ]]; then
    cp "$REPO_ROOT/runHUC.py" "$DEST/runHUC.py"
fi

# ---------------------------------------------------------------------------
# QSWATPlus/ パッケージ (プラグイン本体)
# ---------------------------------------------------------------------------
PKG="$DEST/QSWATPlus"

# --- Python ソースファイル ---
# 実行時に必要な .py のみ。開発用・ビルド用は除外する。
EXCLUDE_PY=(
    "setuppyx*.py"
    "postprocess_ui.py"
    "plugin_upload.py"
    "make_uis_new.py"
    "cythoninit.py"          # pyximport による動的コンパイル用 (コンパイル済み .so があれば不要)
    "monkeytype.sqlite3"
    "mypy.ini"
)

find "$PLUGIN_SRC" -maxdepth 1 -name "*.py" | sort | while read -r f; do
    base="$(basename "$f")"
    skip=0
    for pat in "${EXCLUDE_PY[@]}"; do
        # shellcheck disable=SC2254
        case "$base" in $pat) skip=1; break;; esac
    done
    [[ $skip -eq 1 ]] && continue
    cp "$f" "$PKG/$base"
done

# --- Cython 型ヒント ---
find "$PLUGIN_SRC" -maxdepth 1 -name "*.pyi" -exec cp {} "$PKG/" \;

# --- コンパイル済み Cython 拡張 (Mac Python 3.12 arm64 のみ) ---
for so in "$PLUGIN_SRC"/*.cpython-312-darwin.so; do
    [[ -f "$so" ]] && cp "$so" "$PKG/"
done

# --- QGIS スタイル / テンプレート ---
find "$PLUGIN_SRC" -maxdepth 1 \( -name "*.qml" -o -name "*.qpt" \) \
     -exec cp {} "$PKG/" \;

# --- 画像 / アイコン ---
find "$PLUGIN_SRC" -maxdepth 1 \( -name "*.png" -o -name "*.ico" \) \
     -exec cp {} "$PKG/" \;

# --- Changelog ---
[[ -f "$PLUGIN_SRC/Changelog.txt" ]] && cp "$PLUGIN_SRC/Changelog.txt" "$PKG/"

# --- サブディレクトリ (ランタイムに必要なものだけ) ---
INCLUDE_DIRS=(
    "fonts"        # Ubuntu フォント (UI 用)
    "GlobalData"   # 全球地図データ (DEMなしモード)
    "imageio"      # 動画書き出し用 Python ライブラリ
    "QSWAT-Icon"   # アイコン群
    "SWATPlus"     # プロジェクト DB テンプレート / サンプルデータ
)
for d in "${INCLUDE_DIRS[@]}"; do
    src="$PLUGIN_SRC/$d"
    if [[ -d "$src" ]]; then
        # __pycache__ と .pyc を除外してコピー
        rsync -a \
            --exclude="__pycache__/" \
            --exclude="*.pyc" \
            "$src/" "$PKG/$d/"
    fi
done

# ---------------------------------------------------------------------------
# ZIP 作成
# ---------------------------------------------------------------------------
echo ">>> ZIP を作成しています..."
(cd "$WORK" && zip -r -q "$OUTPUT_ZIP" "$PLUGIN_NAME")

SIZE=$(du -sh "$OUTPUT_ZIP" | cut -f1)
echo ">>> 完了: $OUTPUT_ZIP ($SIZE)"

# ---------------------------------------------------------------------------
# 内容サマリー
# ---------------------------------------------------------------------------
echo ""
echo "=== パッケージ内容 ==="
(cd "$WORK" && find "$PLUGIN_NAME" -type f \
    | grep -v "__pycache__" \
    | sort \
    | awk -F/ 'NF<=3 {print}' \
    | head -60)
echo "  ..."
echo "合計ファイル数: $(cd "$WORK" && find "$PLUGIN_NAME" -type f | wc -l | tr -d ' ')"

# ---------------------------------------------------------------------------
# QGIS への直接インストール (--install 指定時)
# ---------------------------------------------------------------------------
if [[ $DO_INSTALL -eq 1 ]]; then
    echo ""
    echo ">>> QGIS プラグインディレクトリへインストールしています..."
    INSTALL_DEST="$QGIS_PLUGIN_DIR/$PLUGIN_NAME"

    # 既存インストールを退避
    if [[ -d "$INSTALL_DEST" ]]; then
        BACKUP="$INSTALL_DEST.bak"
        rm -rf "$BACKUP"
        mv "$INSTALL_DEST" "$BACKUP"
        echo "  旧バージョンを退避: $(basename "$BACKUP")"
    fi

    mkdir -p "$QGIS_PLUGIN_DIR"
    (cd "$QGIS_PLUGIN_DIR" && unzip -q "$OUTPUT_ZIP")
    echo "  インストール先: $INSTALL_DEST"
    echo ">>> QGIS を再起動してプラグインを有効化してください。"
fi
