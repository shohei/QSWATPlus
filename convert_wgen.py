#!/usr/bin/env python3
"""
convert_wgen.py
===============
ArcSWAT 形式の WGEN_user.csv を SWAT+ Editor の 2 ファイル形式に変換する。

SWAT+ Editor の "Two CSV files" インポートが要求するフォーマット:
  wgn_stat.csv  ... id, name, lat, lon, elev, rain_yrs
  wgn_mon.csv   ... id, wgn_id, month, tmp_max_ave, ...（月別、1 局 12 行）

使い方:
  python3 convert_wgen.py [入力CSV] [出力ディレクトリ]

引数省略時:
  入力CSV      : このスクリプトと同じディレクトリの WGEN_user.csv
  出力ディレクトリ: このスクリプトと同じディレクトリ
"""

import csv
import os
import sys


# ---------------------------------------------------------------------------
# ArcSWAT 形式の列名プレフィクス → SWAT+ DB 列名 のマッピング（月番号は後付け）
# ---------------------------------------------------------------------------
MONTHLY_MAP = [
    ('TMPMX',    'tmp_max_ave'),
    ('TMPMN',    'tmp_min_ave'),
    ('TMPSTDMX', 'tmp_max_sd'),
    ('TMPSTDMN', 'tmp_min_sd'),
    ('PCPMM',    'pcp_ave'),
    ('PCPSTD',   'pcp_sd'),
    ('PCPSKW',   'pcp_skew'),
    ('PR_W1_',   'wet_dry'),
    ('PR_W2_',   'wet_wet'),
    ('PCPD',     'pcp_days'),
    ('RAINHHMX', 'pcp_hhr'),
    ('SOLARAV',  'slr_ave'),
    ('DEWPT',    'dew_ave'),
    ('WNDAV',    'wnd_ave'),
]

STAT_HEADER = ['id', 'name', 'lat', 'lon', 'elev', 'rain_yrs']
MON_HEADER  = ['id', 'wgn_id', 'month'] + [col for _, col in MONTHLY_MAP]


def convert(src_csv: str, out_dir: str) -> None:
    """WGEN_user.csv を読み込み、wgn_stat.csv と wgn_mon.csv を生成する。"""

    if not os.path.isfile(src_csv):
        print(f'ERROR: 入力ファイルが見つかりません: {src_csv}', file=sys.stderr)
        sys.exit(1)

    os.makedirs(out_dir, exist_ok=True)
    out_stat = os.path.join(out_dir, 'wgn_stat.csv')
    out_mon  = os.path.join(out_dir, 'wgn_mon.csv')

    # utf-8-sig で開くと BOM (﻿) を自動除去
    with open(src_csv, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print('ERROR: 入力ファイルにデータ行がありません。', file=sys.stderr)
        sys.exit(1)

    # 必須列の存在確認
    required_sta = ['OBJECTID', 'STATION', 'WLATITUDE', 'WLONGITUDE', 'WELEV', 'RAIN_YRS']
    missing = [c for c in required_sta if c not in rows[0]]
    if missing:
        print(f'ERROR: 以下の列が見つかりません: {missing}', file=sys.stderr)
        print(f'  実際の列: {list(rows[0].keys())[:10]} ...', file=sys.stderr)
        sys.exit(1)

    with open(out_stat, 'w', newline='', encoding='utf-8') as fs, \
         open(out_mon,  'w', newline='', encoding='utf-8') as fm:

        ws = csv.writer(fs)
        wm = csv.writer(fm)
        ws.writerow(STAT_HEADER)
        wm.writerow(MON_HEADER)

        mon_id = 1
        for row in rows:
            sta_id   = int(float(row['OBJECTID']))
            sta_name = row['STATION'].strip()
            lat      = float(row['WLATITUDE'])
            lon      = float(row['WLONGITUDE'])
            elev     = float(row['WELEV'])
            rain_yrs = int(float(row['RAIN_YRS']))

            ws.writerow([sta_id, sta_name, lat, lon, elev, rain_yrs])

            for month in range(1, 13):
                mon_vals = [mon_id, sta_id, month]
                for prefix, _ in MONTHLY_MAP:
                    key = f'{prefix}{month}'
                    try:
                        mon_vals.append(float(row[key]))
                    except (KeyError, ValueError):
                        print(f'  WARNING: 列 "{key}" が読み取れません'
                              f'（局={sta_name}, 月={month}）')
                        mon_vals.append('')
                wm.writerow(mon_vals)
                mon_id += 1

    n = len(rows)
    print(f'変換完了: {n} 局 × 12 ヶ月 = {n * 12} 行')
    print(f'  {out_stat}')
    print(f'  {out_mon}')
    print()
    print('次の手順:')
    print('  SWAT+ Editor > Import Data > Weather Generator')
    print('  > Two CSV files を選択')
    print(f'  > Station CSV : {out_stat}')
    print(f'  > Monthly CSV : {out_mon}')


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))

    src_csv = sys.argv[1] if len(sys.argv) > 1 else os.path.join(script_dir, 'WGEN_user.csv')
    out_dir = sys.argv[2] if len(sys.argv) > 2 else script_dir

    print(f'入力: {src_csv}')
    print(f'出力ディレクトリ: {out_dir}')
    print()
    convert(src_csv, out_dir)
