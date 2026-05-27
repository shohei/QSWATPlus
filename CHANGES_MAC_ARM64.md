# QSWATPlus macOS ARM64 対応 変更履歴

バージョン: 3.2.2  
対象プラットフォーム: macOS (Apple Silicon / arm64)  
QGIS バージョン: 3.44.6-Solothurn

---

## 背景と問題

SRTM 30m DEM を使用した流域区分において、macOS ARM64 環境では Windows (x86_64) と比べて
ストリームネットワークが断片化・不連続になる問題が発生していた。

**根本原因:**

1. **整数標高 DEM でのバーン処理**: SRTM DEM は 1m 分解能の整数値。参照ストリーム上の
   隣接セルが 461m/463m のように交互に異なる場合、均一なバーン深度（例: 50m）を適用すると
   バーン後の標高が 411m/413m と交互になる。これにより局所的な凹地（pit）が連続し、
   TauDEM の PitRemove がこれらを同一「溢れ標高」まで充填 → チャンネル上にフラットパッチが発生。

2. **TauDEM フラットセル解決のプラットフォーム依存性**: TauDEM はフラットセルの D8 方向を
   BFS 的な反復で決定するが、その反復順序が ARM64 (NEON) と x86_64 (SSE) で異なるため、
   同じ DEM から異なるフロー方向ラスタが生成される。

---

## 変更内容

### 1. `QSWATPlus/QSWATTopology.py` — `burnStream()` の全面改修

#### 1-a. 出力形式を Float32 に変更

```
変更前: demDs をコピー → 入力 DEM と同じ型（通常 Int16）
変更後: gdal.GDT_Float32 で新規作成
```

**理由:** バーン勾配値（0.0001 m/セル など）は Int16 では表現できず丸め誤差で失われる。
Float32 により TauDEM PitRemove が正確な傾斜を検出できる。

#### 1-b. 縦断勾配（ストリーム沿い）の追加

チャンネルセルに 2 種類の縦断勾配を重ねて適用する:

| 勾配種別 | 計算式 | 目的 |
|---------|--------|------|
| 標高ベース | `(max_stream_elev - cell_elev) * 0.001` | 下流ほど多くバーン（標高差を利用） |
| カウンターベース | `cell_counter * 0.0001 m/セル` | フラット区間の補助（Bresenham スワップ修正済み） |

これにより隣接するチャンネルセル間に必ず標高差が生じ、TauDEM がフラット解決を行う必要がなくなる。

#### 1-c. Bresenham スワップ修正

```python
if swap_occurred:
    seg_cells = seg_cells[::-1]
```

Bresenham アルゴリズムは `x0 > x1` の場合に端点を入れ替えて描画する。
この場合カウンターが逆順（上流 → 下流）に増加してしまうため、
スワップが発生したセグメントではセルリストを反転してカウンターを正しい向きにする。

#### 1-d. 10 リング BFS 横断勾配（断面の谷形状）

チャンネルから半径 10 セル（30m DEM で約 300m）まで BFS でリング展開し、
リング距離に応じてバーン量を線形減衰させる。これにより D8 がチャンネルへ向かう
滑らかな谷形状を形成する。

```
リング 1: 5/6 × depth
リング 2: 4/6 × depth
...
リング 5: 1/6 × depth
リング 6〜10: 漸減
```

位置ベース補助勾配 `(row + 2*col) * 1e-4 m` をリングセルにも適用し、
同距離のセル間でも D8 タイが発生しないようにする。

---

### 2. `QSWATPlus/TauDEMUtils.py` — `conditionFlatStreamCells()` 追加

**呼び出しタイミング:** PitRemove 実行後 → D8FlowDir 実行前

```python
TauDEMUtils.conditionFlatStreamCells(felFile, burnFile, self._gv.isBatch)
```

#### 処理概要

1. `felFile`（PitRemove 出力）を読み込む
2. フラットセルを検出: 3×3 近傍の最大値 == 最小値
3. 参照ストリームシェープファイルを Bresenham でラスタライズし、各ストリームセルの
   正規化フロー方向ベクトル `(norm_dc, norm_dr)` を記録
4. `flat_stream = flat_mask & stream_on_grid` の連結成分を `scipy.ndimage.label` で識別
5. 各連結成分内で:
   - 平均フロー方向を計算
   - 各セルをフロー軸に射影: `proj = dc_mean * col + dr_mean * row`
   - 射影値で上流/下流を判定: `frac = (proj - proj_min) / (proj_max - proj_min)`
   - 下流ほど多く低下: `fel[cells] -= frac * 0.001 m`
6. Float32 で上書き保存

**対象:** ストリーム上のフラットセルのみ（平野・湖沼などのフラットセルは変更しない）

**ログ出力例:**
```
conditionFlatStreamCells: gradient applied to 2850 flat stream cells (127 components) in 340ms
```

#### 追加インポート（モジュールレベル）

```python
import math
import time
import numpy as np
from osgeo import gdal
from qgis.core import QgsProject, QgsVectorLayer
```

---

### 3. `QSWATPlus/delineation.py` — `conditionFlatStreamCells` 呼び出し追加

```python
# runPitFill の直後、runD8FlowDir の直前に挿入
self._gv.felFile = felFile
if self._dlg.checkBurn.isChecked() and burnFile:
    TauDEMUtils.conditionFlatStreamCells(felFile, burnFile, self._gv.isBatch)
sd8File = base + 'sd8' + suffix
```

`burnFile` は `checkBurn.isChecked()` が True の場合のみ定義されるが、
Python の短絡評価により `checkBurn` が False のときは `burnFile` を評価しない。

---

### 4. `package_mac.sh` — `--install` オプション追加

```bash
./package_mac.sh --install
```

ZIP 作成後に QGIS プラグインディレクトリへ直接展開してインストールする。
既存インストールは `.bak` として退避する。

---

### 5. `setup_taudem_mac.sh` — TauDEM 環境構築スクリプト（新規追加）

TauDEM を macOS ARM64 で動かすために必要な一連のセットアップを自動化する。

```bash
./setup_taudem_mac.sh [TauDEM バイナリディレクトリ]
# デフォルト: ~/SWATPlus/TauDEM5Bin
```

スクリプトが行う処理:

| ステップ | 処理 |
|---------|------|
| 1 | 必須バイナリ（pitremove, d8flowdir, aread8, threshold, streamnet など）の存在確認 |
| 2 | macOS Quarantine 属性の除去（`xattr -d com.apple.quarantine`） |
| 3 | `libgdal.33.dylib` → QGIS `libgdal.38.dylib` のシンボリックリンク作成 |
| 4 | `moveoutletstostreams` コマンドの作成（`moveoutletstostrm` のコピー） |
| 5 | 各バイナリの起動テスト |

#### TauDEM バージョンと GDAL の関係

TauDEM 5.3.8 プリビルドバイナリは GDAL 3.7.x の ABI (`libgdal.33.dylib`) にリンクされている。
macOS 環境には以下の GDAL が存在する:

| ライブラリ | バージョン | 場所 |
|------------|-----------|------|
| `libgdal.39.dylib` | GDAL 3.13 (Homebrew) | `/opt/homebrew/opt/gdal/lib/` |
| `libgdal.38.dylib` | GDAL 3.12 (QGIS 同梱) | `/Applications/QGIS.app/Contents/Frameworks/` |

**TauDEM 5.4.0 ビルド試行と断念:**
```
cmake ../src -DCMAKE_BUILD_TYPE=Release ...
make -j8   # ビルド成功
→ 実行時: SIGBUS (address alignment) in GDALDataset::GetExtent → tiffIOC2
         ARM64 上での GDAL 3.13 の新 API がクラッシュ
→ 採用見送り。~/SWATPlus/TauDEM5Bin_v540_crash に退避済み
```

**解決策:** TauDEM 5.3.8 を維持しつつ、GDAL 3.13 との直接リンクを避ける。

```bash
# Homebrew の libgdal.33 シンボリックリンクを QGIS の libgdal.38 に向ける
ln -sf /Applications/QGIS.app/Contents/Frameworks/libgdal.38.dylib \
        /opt/homebrew/opt/gdal/lib/libgdal.33.dylib
```

QGIS は `@loader_path` RPATH で自己完結しているため、このシンボリックリンクが
QGIS 本体の動作に影響することはない。

#### MacPrefix（TauDEMUtils.py の環境変数）

TauDEM 実行コマンドの先頭に付加する環境変数:

```python
MacPrefix = 'export GDAL_DATA=/opt/homebrew/share/gdal; '
            'export PROJ_LIB=/opt/homebrew/share/proj; '
            'export GDAL_PAM_ENABLED=NO; '
```

- `GDAL_DATA` / `PROJ_LIB`: Homebrew のデータディレクトリを使用
  （QGIS パス `Contents/Resources/qgis/gdal` より断片化が少ない実績）
- `GDAL_PAM_ENABLED=NO`: TauDEM が `.aux.xml` 補助ファイルを書かないよう抑制
  （ただし TauDEM が書く統計情報はこれでは抑制されない — 非致命的）

---

## ビルド・デプロイ手順

### TauDEM 環境の初回セットアップ

```bash
# TauDEM 5.3.8 バイナリを ~/SWATPlus/TauDEM5Bin/ に配置後:
./setup_taudem_mac.sh
```

### Cython 拡張のリビルド（今回は不要）

`.pyx` ファイルは変更していないため、`build_cython_mac.sh` の再実行は**不要**。
既存の `.cpython-312-darwin.so` をそのまま使用できる。

```bash
# 変更した .pyx がある場合のみ実行
./build_cython_mac.sh
```

### プラグインのパッケージ化とインストール

```bash
# ZIP 作成 + QGIS プラグインディレクトリへ直接インストール
./package_mac.sh --install

# ZIP のみ作成（手動配置の場合）
./package_mac.sh
```

### 手動デプロイ（個別ファイルの更新）

```bash
PLUGIN="$HOME/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/QSWATPlusMac3_64/QSWATPlus"
cp QSWATPlus/TauDEMUtils.py   "$PLUGIN/TauDEMUtils.py"
cp QSWATPlus/delineation.py   "$PLUGIN/delineation.py"
cp QSWATPlus/QSWATTopology.py "$PLUGIN/QSWATTopology.py"
```

---

## テスト時の注意

再テストの際は以下の TauDEM 中間ファイルを削除してから QGIS で再実行する:

```bash
DEM_DIR="$HOME/Downloads/swattest6/swat/Watershed/Rasters/DEM"
SHP_DIR="$HOME/Downloads/swattest6/swat/Watershed/Shapes"

# PitRemove 以降の全成果物を削除（バーン済み DEM は保持）
rm -f "$DEM_DIR/SRTM_30m_DEMfel.tif"
rm -f "$DEM_DIR/SRTM_30m_DEMp.tif"  "$DEM_DIR/SRTM_30m_DEMsd8.tif"
rm -f "$DEM_DIR/SRTM_30m_DEMad8.tif" "$DEM_DIR/SRTM_30m_DEMsca.tif"
rm -f "$DEM_DIR/SRTM_30m_DEMslp.tif" "$DEM_DIR/SRTM_30m_DEMang.tif"
rm -f "$DEM_DIR/SRTM_30m_DEMgord.tif" "$DEM_DIR/SRTM_30m_DEMplen.tif"
rm -f "$DEM_DIR/SRTM_30m_DEMtlen.tif"
rm -f "$DEM_DIR/SRTM_30m_DEMsrc"*.tif "$DEM_DIR/SRTM_30m_DEMord"*.tif
rm -f "$DEM_DIR/SRTM_30m_DEMw"*.tif   "$DEM_DIR/SRTM_30m_DEMw"*.prj
rm -f "$DEM_DIR/SRTM_30m_DEMtree"*.dat "$DEM_DIR/SRTM_30m_DEMcoord"*.dat
rm -f "$SHP_DIR/SRTM_30m_DEMchannel".* "$SHP_DIR/SRTM_30m_DEMstream".*
```

---

## 期待される改善

| 指標 | 変更前 | 変更後（期待） |
|------|--------|----------------|
| TauDEM フラットセル数 | 232,877 | 大幅減少（チャンネル上のフラットが解消） |
| チャンネルセル数 | 33,824〜42,195 | Windows と近い値に収束 |
| ストリームの連続性 | 断片化あり | 連続したネットワーク |

QGIS メッセージログ（フィルタ: `QSWATPlus`）に以下が出力されれば成功:
```
conditionFlatStreamCells: gradient applied to XXXX flat stream cells (YYY components) in ZZZms
```

---

## 未使用コード（参考）

`TauDEMUtils.agreeFlatConditioning()` はストリーム周辺の**全フラットセル**に
BFS 距離ベースの勾配を適用する実装（AGREE 手法）。平野全体が変化しすぎて
チャンネルが消失する問題があったため採用せず、現在は未呼び出し。
削除しても動作に影響なし。
