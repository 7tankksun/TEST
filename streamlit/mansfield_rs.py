"""
Mansfield-style weekly RS vs prior N-week mean of weekly RS, plus legacy 63-trading-day RS vs benchmark.

Used by kospi_export_core, kosdaq_export_core, and stage2_from_cache (테마).
"""

from __future__ import annotations

import math
import os
from typing import Literal

import pandas as pd

Market = Literal["kospi", "kosdaq", "tema"]


def relative_strength_ratio(
    stock_close: pd.Series, bench_close: pd.Series | None, lookback: int = 63
) -> float | None:
    if bench_close is None or bench_close.empty or len(stock_close) < lookback + 1:
        return None
    aligned = bench_close.reindex(stock_close.index).ffill()
    s_end = float(stock_close.iloc[-1])
    s_start = float(stock_close.iloc[-(lookback + 1)])
    b_end = float(aligned.iloc[-1])
    b_start = float(aligned.iloc[-(lookback + 1)])
    if any(map(lambda x: pd.isna(x) or x <= 0, (s_start, s_end, b_start, b_end))):
        return None
    return (s_end / s_start) / (b_end / b_start)


def mansfield_weekly_rs_vs_52w_mean(
    stock_close: pd.Series,
    bench_close: pd.Series | None,
    *,
    weeks: int = 52,
) -> dict[str, float] | None:
    """
    Mansfield RS: 최근 1주의 주간 상대 RS가 직전 `weeks`주 평균 대비 얼마나 큰지.

    - 주간 종가: 일봉을 금요일 기준(`W-FRI`)으로 리샘플한 마지막 종가.
    - 주간 RS = (종목 주간 수익률) / (지수 주간 수익률).
    - 반환 `ratio` = (가장 최근 주의 RS) / (그 직전 `weeks`개 주의 RS 산술평균).
    """

    if bench_close is None or bench_close.empty or weeks < 8:
        return None
    s0 = stock_close.sort_index().astype(float)
    b0 = bench_close.reindex(s0.index).ffill().astype(float)
    combo = pd.DataFrame({"s": s0, "b": b0}).dropna(how="any")
    combo = combo[~combo.index.duplicated(keep="last")]
    if len(combo) < 260:
        return None
    idx = pd.to_datetime(combo.index, errors="coerce")
    combo = combo.set_index(idx).sort_index()
    combo = combo.loc[~combo.index.isna()]
    if getattr(combo.index, "tz", None) is not None:
        combo.index = combo.index.tz_convert("Asia/Seoul").tz_localize(None)
    weekly = pd.DataFrame(
        {
            "s": combo["s"].resample("W-FRI", label="right", closed="right").last(),
            "b": combo["b"].resample("W-FRI", label="right", closed="right").last(),
        }
    ).ffill()
    weekly = weekly.dropna(how="any")
    if len(weekly) < weeks + 3:
        return None
    rs_w = (weekly["s"] / weekly["s"].shift(1)) / (weekly["b"] / weekly["b"].shift(1))
    rs_w = rs_w.replace([float("inf"), float("-inf")], pd.NA).dropna()
    if len(rs_w) < weeks + 1:
        return None
    cur = float(rs_w.iloc[-1])
    past = rs_w.iloc[-(weeks + 1) : -1]
    if past.empty:
        return None
    m = float(past.mean())
    if cur <= 0 or m <= 0 or math.isnan(cur) or math.isnan(m):
        return None
    return {
        "ratio": cur / m,
        "weekly_rs_current": cur,
        "weekly_rs_mean_52w": m,
        "weeks_window": float(weeks),
    }


def resolve_rs_for_score(
    stock_close: pd.Series,
    bench_close: pd.Series | None,
    market: Market = "kospi",
) -> tuple[float | None, float, float, dict[str, float | str]]:
    """RS 값·점수용 floor/slope·JSON 부가필드. 기본: Mansfield 주간 대비 직전 N주 평균."""

    keys = {
        "kospi": ("KOSPI_RS_MODE", "KOSPI_MANSFIELD_WEEKS"),
        "kosdaq": ("KOSDAQ_RS_MODE", "KOSDAQ_MANSFIELD_WEEKS"),
        "tema": ("TEMA_RS_MODE", "TEMA_MANSFIELD_WEEKS"),
    }
    mode_key, weeks_key = keys[market]
    mode = (os.environ.get(mode_key) or "mansfield").strip().lower()
    extra: dict[str, float | str] = {}
    if mode == "mansfield":
        try:
            wk = int((os.environ.get(weeks_key) or "52").strip() or "52")
        except ValueError:
            wk = 52
        mf = mansfield_weekly_rs_vs_52w_mean(stock_close, bench_close, weeks=wk)
        if mf is not None:
            try:
                rf = float(os.environ.get("SCORE_RS_FLOOR_MANSFIELD", "1.0"))
            except ValueError:
                rf = 1.0
            try:
                sl = float(os.environ.get("SCORE_RS_MANSFIELD_SLOPE", "100"))
            except ValueError:
                sl = 100.0
            extra = {
                "rs_model": "mansfield_weekly_52w",
                "mansfield_weekly_rs": mf["weekly_rs_current"],
                "mansfield_rs_mean_52w": mf["weekly_rs_mean_52w"],
                "mansfield_weeks": mf["weeks_window"],
            }
            return float(mf["ratio"]), rf, sl, extra
        extra = {"rs_model": "mansfield_fallback_legacy_63d"}
    else:
        extra = {"rs_model": "legacy_63d"}
    try:
        rf = float(os.environ.get("SCORE_RS_FLOOR", "0.92"))
    except ValueError:
        rf = 0.92
    return relative_strength_ratio(stock_close, bench_close), rf, 90.0, extra
