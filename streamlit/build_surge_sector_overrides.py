# -*- coding: utf-8 -*-
"""
LLM으로 surge_sector_overrides.json 을 채움 (미분류 티커만).

  cd streamlit
  set OPENAI_API_KEY=...
  py -3 build_surge_sector_overrides.py

옵션
  --cache-dir   universe_meta.json 위치 (기본 tema_cache_data/cache)
  --max         최대 티커 수
  --batch-size  API당 종목 수 (기본 35)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _load_meta(cache_dir: Path) -> dict[str, dict]:
    p = cache_dir / "universe_meta.json"
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("items") or {}
    except Exception:
        return {}


def main() -> int:
    from candidates_data import CANDIDATES, STANDARD_SECTOR_LABELS
    from surge_sector_resolve import (
        load_surge_sector_overrides,
        merge_surge_sector_overrides,
        resolve_surge_sector,
    )

    ap = argparse.ArgumentParser(description="LLM → surge_sector_overrides.json")
    ap.add_argument("--cache-dir", default=str(HERE / "tema_cache_data" / "cache"))
    ap.add_argument("--max", type=int, default=800, help="처리할 미분류 상한")
    ap.add_argument("--batch-size", type=int, default=35)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    meta = _load_meta(cache_dir)
    if not meta:
        print(f"[SKIP] universe_meta 없음: {cache_dir / 'universe_meta.json'}")
        return 1

    pending: list[tuple[str, str]] = []
    for tkr, m in sorted(meta.items()):
        t = str(tkr).strip().upper()
        name = str((m or {}).get("name") or "").strip()
        info = CANDIDATES.get(t, [])
        ex = str(info[1] or "") if isinstance(info, (list, tuple)) and len(info) > 1 else ""
        cand_sec = ""
        if isinstance(info, (list, tuple)) and len(info) > 1:
            raw = str(info[1] or "")
            if " - " in raw:
                cand_sec = raw.split(" - ", 1)[1].strip()
            else:
                cand_sec = raw
        r = resolve_surge_sector(ticker=t, name=name, payload_sector=cand_sec or "미분류", extra_hint=ex)
        if r == "미분류":
            pending.append((t, name))
        if len(pending) >= int(args.max):
            break

    print(f"미분류 대상: {len(pending)} (상한 {args.max})")
    if not pending:
        return 0

    if args.dry_run:
        print("[dry-run] OPENAI 호출 생략")
        return 0

    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        print("[FAIL] OPENAI_API_KEY 없음")
        return 1

    try:
        from openai import OpenAI
    except ImportError:
        print("[FAIL] openai 패키지 없음")
        return 1

    model = (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
    client = OpenAI(api_key=api_key)
    cats_json = json.dumps(list(STANDARD_SECTOR_LABELS), ensure_ascii=False)

    load_surge_sector_overrides()
    merged: dict[str, str] = {}
    batch_n = max(5, min(80, int(args.batch_size)))

    for start in range(0, len(pending), batch_n):
        chunk = pending[start : start + batch_n]
        lines = "\n".join(f"{t}\t{n}" for t, n in chunk)
        user = (
            "각 줄: 티커, 탭(ASCII), 종목명. 아래 표준 섹터 라벨 **중 정확히 하나**만 골라 JSON 객체만 응답.\n"
            f"허용 라벨: {cats_json}\n"
            "형식: {{\"TICKER\":\"라벨\", ...}} 티커는 입력과 동일(대문자 .KS/.KQ).\n"
            "애매하면 가장 가까운 하나. 절대 임의 한글 새 라벨 금지.\n\n"
            f"{lines}"
        )
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You return only valid JSON objects mapping stock tickers to sector labels from the allowed list. No markdown.",
                    },
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            text = (resp.choices[0].message.content or "").strip()
            data = json.loads(text)
            if not isinstance(data, dict):
                continue
            for k, v in data.items():
                ks = str(k).strip().upper()
                vs = str(v).strip()
                if vs not in STANDARD_SECTOR_LABELS:
                    continue
                merged[ks] = vs
        except Exception as ex:
            print(f"[WARN] batch {start}: {ex}")

    n = merge_surge_sector_overrides(merged)
    print(f"[OK] surge_sector_overrides.json 갱신 항목: {n}, 이번 API 병합 키: {len(merged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
