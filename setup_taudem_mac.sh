#!/usr/bin/env bash
# setup_taudem_mac.sh
# macOS ARM64 で TauDEM 5.3.8 を QSWATPlus から動かすための環境構築スクリプト。
#
# このスクリプトが行うこと:
#   1. TauDEM 5.3.8 バイナリの確認
#   2. macOS Quarantine 属性の除去
#   3. libgdal.33.dylib → QGIS libgdal.38.dylib のシンボリックリンク作成
#   4. moveoutletstostreams コマンドの作成（moveoutletstostrm のコピー）
#   5. 動作確認テスト
#
# 前提条件:
#   - TauDEM 5.3.8 バイナリが ~/SWATPlus/TauDEM5Bin/ に配置済み
#     公式配布版: https://github.com/dtarb/TauDEM/releases/tag/v5.3.8
#     (macOS ARM64 向けのプリビルドを使用すること。5.4.0 は ARM64 SIGBUS クラッシュあり)
#   - QGIS 3.x が /Applications/QGIS.app または /Applications/QGIS-LTR.app にある
#   - Homebrew の open-mpi がインストール済み: brew install open-mpi
#
# 背景:
#   TauDEM 5.3.8 は GDAL 3.7.x の ABI (libgdal.33.dylib) にリンクされている。
#   macOS ARM64 で Homebrew の GDAL は 3.13 (libgdal.39) だが、ABI が変わっており
#   互換シムリンクは動作しない。一方 QGIS 3.44+ は libgdal.38 (GDAL 3.12) を
#   Contents/Frameworks に同梱しており、GDAL 3.7/3.8 との ABI 互換性がある。
#   そのため libgdal.33 → QGIS の libgdal.38 とリンクするのが最も安定した解決策。
#
#   TauDEM 5.4.0 をソースから ARM64 ネイティブビルドすると cmake は成功するが、
#   実行時に GDAL 3.13 の GetExtent 内 (tiffIOC2) で SIGBUS が発生してクラッシュ
#   するため、採用しない。
#
# 使い方:
#   ./setup_taudem_mac.sh [TauDEM バイナリディレクトリ]
#   例: ./setup_taudem_mac.sh ~/SWATPlus/TauDEM5Bin

set -euo pipefail

# ---------------------------------------------------------------------------
# 引数 / パス設定
# ---------------------------------------------------------------------------
TAUDEM_DIR="${1:-$HOME/SWATPlus/TauDEM5Bin}"

if [[ ! -d "$TAUDEM_DIR" ]]; then
    echo "ERROR: TauDEM ディレクトリが見つかりません: $TAUDEM_DIR" >&2
    echo "  TauDEM 5.3.8 バイナリを以下に配置してください:" >&2
    echo "  https://github.com/dtarb/TauDEM/releases/tag/v5.3.8" >&2
    exit 1
fi

# QGIS アプリの検出
if [[ -d "/Applications/QGIS-LTR.app" ]]; then
    QGIS_APP="/Applications/QGIS-LTR.app"
elif [[ -d "/Applications/QGIS.app" ]]; then
    QGIS_APP="/Applications/QGIS.app"
else
    echo "ERROR: QGIS が見つかりません (/Applications/QGIS.app または /Applications/QGIS-LTR.app)" >&2
    exit 1
fi

QGIS_LIBGDAL="$QGIS_APP/Contents/Frameworks/libgdal.38.dylib"

echo ">>> TauDEM ディレクトリ: $TAUDEM_DIR"
echo ">>> QGIS:               $QGIS_APP"
echo ""

# ---------------------------------------------------------------------------
# ステップ 1: TauDEM バイナリの存在確認
# ---------------------------------------------------------------------------
echo "--- [1/5] TauDEM バイナリ確認 ---"
REQUIRED_BINS=(pitremove d8flowdir aread8 threshold streamnet
               moveoutletstostrm d8hdisttostrm dinfflowdir)
MISSING=0
for bin in "${REQUIRED_BINS[@]}"; do
    if [[ -x "$TAUDEM_DIR/$bin" ]]; then
        echo "  OK: $bin"
    else
        echo "  MISSING: $bin"
        MISSING=1
    fi
done
if [[ $MISSING -eq 1 ]]; then
    echo ""
    echo "ERROR: 必須バイナリが不足しています。" >&2
    echo "  TauDEM 5.3.8 バイナリを $TAUDEM_DIR に配置してください。" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# ステップ 2: macOS Quarantine 属性の除去
# ---------------------------------------------------------------------------
echo ""
echo "--- [2/5] Quarantine 属性の除去 ---"
REMOVED=0
for bin in "$TAUDEM_DIR"/*; do
    if [[ -x "$bin" && -f "$bin" ]]; then
        if xattr "$bin" 2>/dev/null | grep -q "com.apple.quarantine"; then
            xattr -d com.apple.quarantine "$bin" 2>/dev/null && \
                echo "  Removed quarantine: $(basename "$bin")" && \
                REMOVED=$((REMOVED + 1))
        fi
    fi
done
if [[ $REMOVED -eq 0 ]]; then
    echo "  (quarantine 属性なし — 既に除去済みか不要)"
fi

# ---------------------------------------------------------------------------
# ステップ 3: libgdal.33 → QGIS libgdal.38 シンボリックリンク
# ---------------------------------------------------------------------------
echo ""
echo "--- [3/5] libgdal.33 シンボリックリンクの確認 / 作成 ---"

# TauDEM が要求するライブラリパスを確認
TAUDEM_LIBGDAL_REF=$(otool -L "$TAUDEM_DIR/pitremove" 2>/dev/null \
    | grep libgdal | awk '{print $1}')
echo "  TauDEM が参照する libgdal: $TAUDEM_LIBGDAL_REF"

SYMLINK_PATH="$TAUDEM_LIBGDAL_REF"

# QGIS の libgdal.38 が存在するか確認
if [[ ! -f "$QGIS_LIBGDAL" ]]; then
    # バージョン違いの場合でも libgdal.3*.dylib を探す
    QGIS_LIBGDAL=$(ls "$QGIS_APP/Contents/Frameworks/libgdal.3"?.dylib 2>/dev/null | sort -V | tail -1)
    if [[ -z "$QGIS_LIBGDAL" ]]; then
        echo "ERROR: QGIS の libgdal が見つかりません: $QGIS_APP/Contents/Frameworks/" >&2
        exit 1
    fi
fi
echo "  QGIS libgdal:             $QGIS_LIBGDAL"

if [[ -L "$SYMLINK_PATH" ]]; then
    CURRENT_TARGET=$(readlink "$SYMLINK_PATH")
    if [[ "$CURRENT_TARGET" == "$QGIS_LIBGDAL" ]]; then
        echo "  OK: シンボリックリンク既存 ($SYMLINK_PATH -> $QGIS_LIBGDAL)"
    else
        echo "  更新: $SYMLINK_PATH -> $QGIS_LIBGDAL (旧: $CURRENT_TARGET)"
        ln -sf "$QGIS_LIBGDAL" "$SYMLINK_PATH"
    fi
elif [[ -e "$SYMLINK_PATH" ]]; then
    echo "  ERROR: $SYMLINK_PATH はシンボリックリンクではなく実ファイルが存在します。" >&2
    echo "  手動で確認してください。" >&2
    exit 1
else
    echo "  作成: $SYMLINK_PATH -> $QGIS_LIBGDAL"
    ln -sf "$QGIS_LIBGDAL" "$SYMLINK_PATH"
fi

# ---------------------------------------------------------------------------
# ステップ 4: moveoutletstostreams の作成
# ---------------------------------------------------------------------------
echo ""
echo "--- [4/5] moveoutletstostreams コマンド確認 ---"
# QSWATPlus は 'moveoutletstostreams' を呼ぶが、TauDEM 5.3.8 では 'moveoutletstostrm'
STREAMS_BIN="$TAUDEM_DIR/moveoutletstostreams"
STRM_BIN="$TAUDEM_DIR/moveoutletstostrm"

if [[ -x "$STREAMS_BIN" ]]; then
    echo "  OK: moveoutletstostreams 既存"
elif [[ -x "$STRM_BIN" ]]; then
    cp "$STRM_BIN" "$STREAMS_BIN"
    echo "  作成: moveoutletstostreams (moveoutletstostrm のコピー)"
else
    echo "  WARNING: moveoutletstostrm が見つかりません。moveoutletstostreams は作成できません。"
fi

# ---------------------------------------------------------------------------
# ステップ 5: 動作確認テスト
# ---------------------------------------------------------------------------
echo ""
echo "--- [5/5] 動作確認 ---"
# GDAL_DATA と PROJ_LIB は Homebrew のものを使う
# (QGIS パスより断片化が少ない実績あり)
export GDAL_DATA=/opt/homebrew/share/gdal
export PROJ_LIB=/opt/homebrew/share/proj

ERRORS=0
for bin in pitremove d8flowdir aread8 threshold streamnet; do
    result=$(DYLD_FALLBACK_LIBRARY_PATH="$QGIS_APP/Contents/Frameworks" \
             "$TAUDEM_DIR/$bin" --help 2>&1 | head -1 || true)
    # バイナリは引数なしや --help でバージョン行を出力する
    if echo "$result" | grep -qiE "version [0-9]|usage|error 4"; then
        echo "  OK: $bin  ($result)"
    else
        echo "  FAIL: $bin  (出力: ${result:0:80})"
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""
if [[ $ERRORS -eq 0 ]]; then
    echo "=== 全テスト通過 ==="
    echo ""
    echo "TauDEM セットアップ完了。"
    echo ""
    echo "QSWATPlus 側の確認事項:"
    echo "  - TauDEM ディレクトリ設定: $TAUDEM_DIR"
    echo "  - MPI 実行ファイル:         $(command -v mpiexec 2>/dev/null || echo 'NOT FOUND — brew install open-mpi')"
    echo ""
    echo "次のステップ: build_cython_mac.sh → package_mac.sh --install → QGIS 再起動"
else
    echo "=== $ERRORS 件のエラーがあります ==="
    echo ""
    echo "よくある原因:"
    echo "  - libgdal.33.dylib のシンボリックリンクが壊れている"
    echo "    → ls -la $SYMLINK_PATH"
    echo "  - open-mpi が未インストール"
    echo "    → brew install open-mpi"
    echo "  - quarantine 属性が残っている"
    echo "    → xattr -d com.apple.quarantine $TAUDEM_DIR/*"
    exit 1
fi
