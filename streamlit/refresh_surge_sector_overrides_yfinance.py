#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""테마 캐시 유니버스에서 `미분류` 티커만 yfinance로 조회해 surge_sector_overrides.json 에 병합."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

from stage2_from_cache import _load_universe_meta, _sector_map_from_candidates, _resolve_sector_row
from surge_sector_resolve import (
    infer_standard_sector_from_yf,
    load_surge_sector_overrides,
    merge_surge_sector_overrides,
)


def _pending_tickers(cache_dir: Path) -> list[str]:
    meta = _load_universe_meta(cache_dir)
    raw = pd.read_parquet(cache_dir / "ohlcv_daily.parquet")
    tickers = sorted(set(raw["ticker"].astype(str)))
    sm = _sector_map_from_candidates()
    out: list[str] = []
    for t in tickers:
        m = meta.get(t, {})
        if _resolve_sector_row(t, sm, m) == "미분류":
            out.append(t)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    ap.add_argument("--cache-dir", type=Path, default=here / "tema_cache_data" / "cache")
    ap.add_argument("--sleep", type=float, default=0.06, help="티커당 대기(초), 과도한 요청 완화")
    ap.add_argument("--limit", type=int, default=0, help="0이면 전체")
    ap.add_argument("--dry-run", action="store_true", help="병합 없이 상위 샘플만 출력")
    args = ap.parse_args()
    cache_dir: Path = args.cache_dir
    if not (cache_dir / "ohlcv_daily.parquet").is_file():
        print(f"[ERR] 캐시 없음: {cache_dir / 'ohlcv_daily.parquet'}", file=sys.stderr)
        return 1

    pending = _pending_tickers(cache_dir)
    before_ov = len(load_surge_sector_overrides())
    if args.limit and args.limit > 0:
        pending = pending[: args.limit]
    print(f"미분류 대상: {len(pending)} (기존 오버라이드 {before_ov}개)")

    new_entries: dict[str, str] = {}
    unresolved: list[str] = []
    meta_all = _load_universe_meta(cache_dir)

    for i, t in enumerate(pending):
        if i and i % 100 == 0:
            print(f"  … {i}/{len(pending)} (누적 매핑 {len(new_entries)})")
        try:
            inf = yf.Ticker(t).info
        except Exception:
            unresolved.append(t)
            time.sleep(args.sleep)
            continue
        if not isinstance(inf, dict) or not inf.get("symbol"):
            unresolved.append(t)
            time.sleep(args.sleep)
            continue
        name_ko = str(meta_all.get(t, {}).get("name") or "")
        label = infer_standard_sector_from_yf(inf, name_ko, ticker=t)
        if label:
            new_entries[t] = label
        else:
            unresolved.append(t)
        time.sleep(max(0.0, float(args.sleep)))

    print(f"yfinance 매핑 성공: {len(new_entries)}, 미해결: {len(unresolved)}")
    if args.dry_run:
        sample = dict(list(new_entries.items())[:25])
        print(json.dumps(sample, ensure_ascii=False, indent=2))
        return 0

    changed = merge_surge_sector_overrides(new_entries)
    after_ov = len(load_surge_sector_overrides())
    print(f"병합 시 변경 키: {changed}, 저장 후 오버라이드 총 {after_ov}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
