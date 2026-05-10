# -*- coding: utf-8 -*-
"""
rank_by_date.json 스냅샷 → Δ1d / Δ3d / Δ6d.

스캔 스냅샷 날짜(asof, 보통 diff_snapshot_date)를 기준으로
달력 **어제 / 3일 전 / 6일 전** 각각에 대해:

1) 해당 YYYY-MM-DD 키의 저장본이 있으면 그것을 사용
2) 없으면 그 날짜 이전(포함) 중 가장 최근 저장일 사용

현재 순위는 각 행의 ``rank`` 필드(전체 Stage2 목록 기준 순위)와 비교합니다.
티커 키는 대소문자 무시로 맞춥니다.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore[misc, assignment]


def normalize_ticker_key(t: str) -> str:
    return str(t or "").strip().upper()


def normalize_sector_key(s: str) -> str:
    return str(s or "").strip()


def load_rank_by_date(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def calendar_today_kst_iso() -> str:
    if ZoneInfo is not None:
        try:
            return datetime.datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        except Exception:
            pass
    return datetime.datetime.now().date().isoformat()


def _coerce_rank_map(
    raw: dict | None,
    key_normalizer,
) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in (raw or {}).items():
        ks = key_normalizer(str(k))
        if not ks:
            continue
        try:
            out[ks] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def best_rank_snapshot_on_or_before(
    rank_hist: dict,
    cutoff_iso: str,
    *,
    key_normalizer,
) -> tuple[str | None, dict[str, int]]:
    """cutoff_iso 이전(포함) 날짜 중 가장 최근 저장분."""

    dates = [d for d in rank_hist.keys() if isinstance(d, str) and len(d) == 10 and d <= cutoff_iso]
    if not dates:
        return None, {}
    dmax = max(dates)
    raw = rank_hist.get(dmax) or {}
    return dmax, _coerce_rank_map(raw if isinstance(raw, dict) else {}, key_normalizer)


def snapshot_for_calendar_reference(
    rank_hist_before_asof: dict,
    ref_calendar_iso: str,
    *,
    key_normalizer,
) -> tuple[str | None, dict[str, int]]:
    """ref_calendar_iso 달력일 스냅샷: 해당 일 키 우선, 없으면 그 전 최신."""

    raw_exact = rank_hist_before_asof.get(ref_calendar_iso)
    if isinstance(raw_exact, dict) and raw_exact:
        return ref_calendar_iso, _coerce_rank_map(raw_exact, key_normalizer)
    return best_rank_snapshot_on_or_before(
        rank_hist_before_asof, ref_calendar_iso, key_normalizer=key_normalizer
    )


def fmt_rank_delta(prev_rank: int | None, curr_rank: int | None) -> str:
    """이전 순위 대비 변화 (+ = 순위 상승, 숫자 감소 방향)."""

    if prev_rank is None or curr_rank is None:
        return "—"
    try:
        pr = int(prev_rank)
        cr = int(curr_rank)
    except (TypeError, ValueError):
        return "—"
    d = pr - cr
    if d == 0:
        return "0"
    return f"+{d}" if d > 0 else str(d)


def attach_rank_deltas_to_rows(
    rows: list,
    rank_hist_before_asof: dict,
    asof_iso: str,
) -> dict[str, str | None]:
    """
    rank_hist_before_asof: asof_iso 를 제외한 과거 일자만(당일 재스캔 시 오늘 스냅샷 자기참조 방지).
    asof_iso: 이번 results_web.json 스냅샷 날짜 (diff_snapshot_date).
    """

    meta: dict[str, str | None] = {}
    norm_t = normalize_ticker_key
    for r in rows:
        r["rank_delta_1d"] = "—"
        r["rank_delta_3d"] = "—"
        r["rank_delta_6d"] = "—"

    try:
        t0 = datetime.date.fromisoformat(asof_iso)
    except ValueError:
        return meta

    offsets = (("1d", 1), ("3d", 3), ("6d", 6))
    snaps: dict[str, tuple[str | None, dict[str, int]]] = {}
    for label, days in offsets:
        ref_cal = (t0 - datetime.timedelta(days=days)).isoformat()
        d_snap, mp = snapshot_for_calendar_reference(
            rank_hist_before_asof, ref_cal, key_normalizer=norm_t
        )
        snaps[label] = (d_snap, mp)
        meta[f"snapshot_{label}"] = d_snap
        meta[f"ref_calendar_{label}"] = ref_cal

    for r in rows:
        tid = norm_t(str(r.get("ticker") or ""))
        try:
            cr = int(r.get("rank"))
        except (TypeError, ValueError):
            cr = None
        for label, _days in offsets:
            _, mp = snaps[label]
            pr = mp.get(tid) if mp and tid else None
            r[f"rank_delta_{label}"] = fmt_rank_delta(pr, cr)

    return meta


def attach_sector_rank_deltas(
    rows: list,
    rank_hist_before_asof: dict,
    asof_iso: str,
) -> dict[str, str | None]:
    meta: dict[str, str | None] = {}
    norm_s = normalize_sector_key
    for r in rows:
        r["rank_delta_1d"] = "—"
        r["rank_delta_3d"] = "—"
        r["rank_delta_6d"] = "—"
    try:
        t0 = datetime.date.fromisoformat(asof_iso)
    except ValueError:
        return meta
    offsets = (("1d", 1), ("3d", 3), ("6d", 6))
    snaps: dict[str, tuple[str | None, dict[str, int]]] = {}
    for label, days in offsets:
        ref_cal = (t0 - datetime.timedelta(days=days)).isoformat()
        d_snap, mp = snapshot_for_calendar_reference(
            rank_hist_before_asof, ref_cal, key_normalizer=norm_s
        )
        snaps[label] = (d_snap, mp)
        meta[f"snapshot_{label}"] = d_snap
        meta[f"ref_calendar_{label}"] = ref_cal
    for r in rows:
        sid = norm_s(str(r.get("sector") or ""))
        try:
            cr = int(r.get("rank"))
        except (TypeError, ValueError):
            cr = None
        for label, _days in offsets:
            _, mp = snaps[label]
            pr = mp.get(sid) if mp and sid else None
            r[f"rank_delta_{label}"] = fmt_rank_delta(pr, cr)
    return meta
