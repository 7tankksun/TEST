"""
코스닥 고정 루트 Stage2 스캔 → NAS 동기화용 results_web.json + charts/ + state/
(로컬 run_local_export.py에서만 실행 권장. NAS는 app_nas_serve_kosdaq가 JSON만 읽음)
state/rank_by_date.json에 일별 순위 스냅샷을 쌓아 상단 요약 표에 Δ1·3·6일 순위 변화를 표시합니다.
"""

from __future__ import annotations

import json
from typing import Any
import logging
import math
import os
import sys
import warnings
import datetime
from collections import OrderedDict

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore[misc, assignment]

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib

matplotlib.use("Agg")
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*Glyph.*", category=UserWarning)
warnings.filterwarnings("ignore", module="matplotlib")

import matplotlib.pyplot as plt

from kosdaq_candidates import CANDIDATES
from mansfield_rs import resolve_rs_for_score
from rank_delta_utils import attach_rank_deltas_to_rows, attach_sector_rank_deltas

# Stage2 점수 기본 비중(환경변수로 오버라이드 가능)
os.environ.setdefault("SCORE_MAX_RS", "58")
os.environ.setdefault("SCORE_MAX_RECENCY", "25")
os.environ.setdefault("SCORE_MAX_VOL_INTERNAL", "20")
os.environ.setdefault("SCORE_MAX_VOL_VS_BENCH", "15")


def _setup_font(base_dir: str):
    font_dir = os.path.join(base_dir, "fonts")
    os.makedirs(font_dir, exist_ok=True)
    if sys.platform == "win32":
        plt.rcParams["font.family"] = "Malgun Gothic"
    else:
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def get_sector(ticker: str) -> str:
    return (CANDIDATES.get(ticker) or ["", "미분류"])[1]


def _universe_counts_by_sector() -> dict[str, int]:
    """후보 유니버스(CANDIDATES) 기준 섹터별 종목 수."""
    out: dict[str, int] = {}
    for tkr in CANDIDATES:
        s = get_sector(tkr)
        out[s] = out.get(s, 0) + 1
    return out


def _normalize_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        except Exception:
            pass
    return df


def _index_normalize_ts(idx: pd.Index) -> pd.DatetimeIndex:
    ts = pd.DatetimeIndex(pd.to_datetime(idx))
    if ts.tz is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _slice_ohlcv_to_asof(df: pd.DataFrame | None, asof: datetime.date, *, min_rows: int) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    ts = _index_normalize_ts(df.index)
    sub = df.loc[ts.normalize() <= pd.Timestamp(asof).normalize()].copy()
    if len(sub) < min_rows:
        return None
    return sub


def _slice_series_to_asof(ser: pd.Series | None, asof: datetime.date) -> pd.Series | None:
    if ser is None or ser.empty:
        return None
    ts = _index_normalize_ts(ser.index)
    sub = ser.loc[ts.normalize() <= pd.Timestamp(asof).normalize()]
    return sub if len(sub) > 0 else None


def _last_ohlcv_bar_date(df: pd.DataFrame | None) -> datetime.date | None:
    if df is None or df.empty:
        return None
    try:
        ts = _index_normalize_ts(df.index)
        return ts.max().date()
    except Exception:
        return None


def _download_bench_kq11_dataframe() -> tuple[pd.DataFrame | None, dict]:
    fail_status = {
        "ticker": "^KQ11",
        "name": "KOSDAQ",
        "is_stage2": None,
        "headline": "코스닥 지수: 다운로드 실패",
        "tone": "unknown",
        "as_of": None,
        "last_close": None,
        "ma50": None,
        "ma200": None,
    }
    try:
        data = yf.download("^KQ11", period="3y", interval="1d", progress=False, auto_adjust=True)
        if data.empty:
            return None, fail_status
        df = _normalize_df_columns(data.copy())
        status = _index_stage2_status_from_ohlcv_df(df, "^KQ11", "코스닥")
        if "Close" not in df.columns:
            return None, status
        return df, status
    except Exception:
        return None, {
            **fail_status,
            "headline": "코스닥 지수: 조회 실패",
        }


def _safe_float(x) -> float | None:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def stage2_episode_start_index(is_stage2: pd.Series) -> int | None:
    if is_stage2.empty or not bool(is_stage2.iloc[-1]):
        return None
    i = len(is_stage2) - 1
    while i >= 0 and bool(is_stage2.iloc[i]):
        i -= 1
    return i + 1


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _index_stage2_status_from_ohlcv_df(
    df: pd.DataFrame, index_ticker: str, display_name: str
) -> dict:
    """
    지수 Stage2 (시장 카드 전용):

    - **엄격(strict)**: Close>MA150>MA200, MA200 20봉 우상, MA50 10봉 상승, 종가>MA50.
    - **완화(relaxed)**: 급등·V반등에서 MA150이 아직 MA200 위로 못 올라온 경우가 많아,
      종가가 MA200·MA150 **모두 위**이고 MA200 우상·MA50 조건은 동일할 때도 2단계로 인정.

    개별 종목 스캐너는 기존 MA150>MA200 스택을 그대로 씀.
    """
    need = 200
    if df is None or df.empty or len(df) < need:
        return {
            "ticker": index_ticker,
            "name": display_name,
            "is_stage2": None,
            "headline": f"{display_name} 지수: 데이터 부족(또는 조회 실패)",
            "tone": "unknown",
            "as_of": None,
            "last_close": None,
            "ma50": None,
            "ma200": None,
        }
    dfn = _normalize_df_columns(df.copy())
    if "Close" not in dfn.columns:
        return {
            "ticker": index_ticker,
            "name": display_name,
            "is_stage2": None,
            "headline": f"{display_name} 지수: 데이터 없음",
            "tone": "unknown",
            "as_of": None,
            "last_close": None,
            "ma50": None,
            "ma200": None,
        }
    c = pd.to_numeric(dfn["Close"], errors="coerce").astype(float)
    dfn = dfn.assign(Close=c)
    dfn = dfn.loc[np.isfinite(dfn["Close"])].copy()
    if len(dfn) < need:
        return {
            "ticker": index_ticker,
            "name": display_name,
            "is_stage2": None,
            "headline": f"{display_name} 지수: 유효 종가 봉 부족(마지막 NaN 등)",
            "tone": "unknown",
            "as_of": None,
            "last_close": None,
            "ma50": None,
            "ma200": None,
        }
    c = dfn["Close"]
    dfn["MA50"] = c.rolling(50).mean()
    dfn["MA150"] = c.rolling(150).mean()
    dfn["MA200"] = c.rolling(200).mean()
    dfn["MA200_Trend"] = dfn["MA200"] > dfn["MA200"].shift(20)
    stage2_zone = (c > dfn["MA150"]) & (dfn["MA150"] > dfn["MA200"]) & (dfn["MA200_Trend"])
    ma50_up = dfn["MA50"].iloc[-1] > dfn["MA50"].iloc[-10]
    price_above_ma50 = c.iloc[-1] > dfn["MA50"].iloc[-1]
    strict_s2 = bool(stage2_zone.iloc[-1]) and bool(ma50_up) and bool(price_above_ma50)

    m150_last = float(dfn["MA150"].iloc[-1])
    last = float(c.iloc[-1])
    m50 = float(dfn["MA50"].iloc[-1])
    m200 = float(dfn["MA200"].iloc[-1])
    if not (
        math.isfinite(last)
        and math.isfinite(m50)
        and math.isfinite(m200)
        and math.isfinite(m150_last)
    ):
        return {
            "ticker": index_ticker,
            "name": display_name,
            "is_stage2": None,
            "headline": f"{display_name} 지수: MA/종가 계산 불가(데이터 이상)",
            "tone": "unknown",
            "as_of": None,
            "last_close": None,
            "ma50": None,
            "ma200": None,
        }
    ts = dfn.index[-1]
    as_of = str(ts.date()) if hasattr(ts, "date") else str(ts)

    relaxed_s2 = (
        bool(ma50_up)
        and bool(price_above_ma50)
        and bool(dfn["MA200_Trend"].iloc[-1])
        and (last > m200)
        and (last > m150_last)
    )
    is_s2 = strict_s2 or relaxed_s2
    stage2_mode = "strict" if strict_s2 else ("relaxed" if relaxed_s2 else "none")

    if is_s2:
        if stage2_mode == "relaxed":
            headline = (
                f"{display_name} : 2단계 상승 — 추세·모멘텀 충족 "
                f"(MA150>MA200 정렬은 아직일 수 있음, 급반등 구간 참고)"
            )
        else:
            headline = f"{display_name} : 2단계 상승 — 시장이 스테이지2 (포지션·진입에 유리)"
        tone = "stage2"
    elif last < m200:
        headline = f"{display_name} : 2단계 아님 — 약세(종가<MA200), 상승 투자엔 경계"
        tone = "bear"
    elif last < m50:
        headline = f"{display_name} : 2단계 아님 — 단기 둔화(종가<MA50)"
        tone = "caution"
    else:
        headline = f"{display_name} : 2단계 아님 — 조정·눌림/횡보 등(지수 2단계 조건 미충족)"
        tone = "weak"

    return {
        "ticker": index_ticker,
        "name": display_name,
        "is_stage2": is_s2,
        "stage2_mode": stage2_mode,
        "headline": headline,
        "tone": tone,
        "as_of": as_of,
        "last_close": round(last, 2),
        "ma50": round(m50, 2),
        "ma200": round(m200, 2),
    }


def _load_bench_kq11() -> tuple[pd.Series | None, pd.Series | None, dict]:
    df, status = _download_bench_kq11_dataframe()
    if df is None or "Close" not in df.columns:
        return None, None, status
    vol = df["Volume"] if "Volume" in df.columns else None
    return df["Close"], vol, status


def _normalize_signal_value(v):
    if isinstance(v, dict):
        return v
    return {"entry": str(v)}


def _load_previous_signals(signal_history_path: str):
    if not os.path.isfile(signal_history_path):
        return {}
    try:
        with open(signal_history_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("tickers") or {}
        return {k: _normalize_signal_value(v) for k, v in raw.items()}
    except Exception:
        return {}


def _calendar_today_iso(tz_name: str) -> str:
    if ZoneInfo is not None:
        try:
            return datetime.datetime.now(ZoneInfo(tz_name)).date().isoformat()
        except Exception:
            pass
    return datetime.datetime.now().date().isoformat()


def _now_wallclock_str_kst() -> str:
    """results_web.json 등에 기록하는 분석 시각 — 컨테이너 TZ와 무관하게 KST."""

    if ZoneInfo is not None:
        try:
            return datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _minimal_tickers_for_history(matches: dict) -> dict:
    out: dict[str, dict] = {}
    for k, v in matches.items():
        if isinstance(v, dict):
            out[k] = {"entry": v.get("entry", "-")}
        else:
            out[k] = {"entry": str(v)}
    return out


def _load_signals_by_date(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_signals_by_date(path: str, hist: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


def _migrate_signals_history_from_last_run(
    history: dict, signal_history_path: str, today_iso: str
) -> dict:
    if history:
        return history
    if not os.path.isfile(signal_history_path):
        return history
    try:
        with open(signal_history_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("tickers") or {}
        if not raw:
            return history
        saved_at = (data.get("saved_at") or "")[:10]
        if len(saved_at) != 10 or saved_at >= today_iso:
            return history
        history[saved_at] = {"tickers": _minimal_tickers_for_history(raw)}
    except Exception:
        pass
    return history


def _prev_signals_for_diff(history: dict, today_iso: str) -> tuple[dict, str | None]:
    """신규·탈락 비교 기준.

    - 우선 당일보다 이른 날짜 중 가장 최근 스냅샷(통상 전일 이전).
    - 없으면 `signals_by_date.json` 안의 당일 스냅샷 — 같은 날 재실행·재배포 후에도 직전 실행분과 비교 가능.
      (오늘 키만 있어도 `d < today` 만으로는 기준을 못 찾아 항상 '첫 이력'이 되던 문제를 막음)
    """
    prior = [d for d in history.keys() if isinstance(d, str) and len(d) == 10 and d < today_iso]
    if prior:
        bd = max(prior)
        raw = (history.get(bd) or {}).get("tickers") or {}
        return {k: _normalize_signal_value(v) for k, v in raw.items()}, bd
    bucket = history.get(today_iso)
    raw = (bucket.get("tickers") or {}) if isinstance(bucket, dict) else {}
    if raw:
        return {k: _normalize_signal_value(v) for k, v in raw.items()}, today_iso
    return {}, None


def _prune_signals_history(hist: dict, today_iso: str, keep_days: int = 400) -> None:
    try:
        t0 = datetime.date.fromisoformat(today_iso)
    except ValueError:
        return
    cutoff = (t0 - datetime.timedelta(days=keep_days)).isoformat()
    for k in list(hist.keys()):
        if isinstance(k, str) and len(k) == 10 and k < cutoff:
            del hist[k]


def _load_diff_daily_log(path: str) -> list:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            log = json.load(f)
        return log if isinstance(log, list) else []
    except Exception:
        return []


def _save_diff_daily_log(path: str, log: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def _load_rank_by_date(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_rank_by_date(path: str, hist: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


def _prune_rank_by_date(hist: dict, today_iso: str, keep_days: int = 400) -> None:
    try:
        t0 = datetime.date.fromisoformat(today_iso)
    except ValueError:
        return
    cutoff = (t0 - datetime.timedelta(days=keep_days)).isoformat()
    for k in list(hist.keys()):
        if isinstance(k, str) and len(k) == 10 and k < cutoff:
            del hist[k]


def _upsert_daily_diff_log(path: str, entry: dict) -> list:
    log = _load_diff_daily_log(path)
    sd = entry.get("snapshot_date")
    log = [e for e in log if e.get("snapshot_date") != sd]
    log.append(entry)
    log = log[-60:]
    _save_diff_daily_log(path, log)
    return log


def _build_diff_lists(prev: dict, new_matches: dict):
    prev_keys = set(prev.keys())
    new_keys = set(new_matches.keys())
    added_keys = sorted(new_keys - prev_keys)
    removed_keys = sorted(prev_keys - new_keys)
    last_diff_added = [
        {
            "ticker": t,
            "name": CANDIDATES.get(t, ["?", "?"])[0],
            "entry": new_matches[t]["entry"],
            "sector": get_sector(t),
            "rank": new_matches[t].get("rank"),
            "score": new_matches[t].get("score"),
            "rs_ratio": new_matches[t].get("rs_ratio"),
            "vol_20_vs_prev20": new_matches[t].get("vol_20_vs_prev20"),
        }
        for t in sorted(added_keys, key=lambda x: (new_matches[x].get("rank") or 9999, x))
    ]
    last_diff_removed = [
        {
            "ticker": t,
            "name": CANDIDATES.get(t, ["?", "?"])[0],
            "entry": prev[t].get("entry", "-"),
            "sector": get_sector(t),
        }
        for t in removed_keys
    ]
    return last_diff_added, last_diff_removed


def _match_rows_from_detail(match_detail: dict) -> list:
    rows = []
    for t, d in match_detail.items():
        display_name = (CANDIDATES.get(t) or [d.get("name", ""), ""])[0]
        rows.append(
            {
                "ticker": t,
                "name": display_name,
                "entry": d["entry"],
                "chart": d.get("chart"),
                "sector": get_sector(t),
                "rank": d["rank"],
                "score": d["score"],
                "score_breakdown": d.get("score_breakdown") or {},
                "bars_since_stage2_entry": d.get("bars_since_stage2_entry"),
                "rs_ratio": d.get("rs_ratio"),
                "ret_since_entry_pct": d.get("ret_since_entry_pct"),
                "ret_daytrade_pct": d.get("ret_daytrade_pct"),
                "ret_swing_pct": d.get("ret_swing_pct"),
                "entry_daytrade": d.get("entry_daytrade"),
                "entry_swing": d.get("entry_swing"),
                "ret_3m_pct": d.get("ret_3m_pct"),
                "close": d.get("close"),
                "ma20": d.get("ma20"),
                "ma50": d.get("ma50"),
                "dist_ma20_pct": d.get("dist_ma20_pct"),
                "dist_ma50_pct": d.get("dist_ma50_pct"),
                "stage2_status": d.get("stage2_status"),
                "vol_5_vs_20": d.get("vol_5_vs_20"),
                "vol_20_vs_prev20": d.get("vol_20_vs_prev20"),
                "vol_vs_bench_ratio": d.get("vol_vs_bench_ratio"),
                "market_cap": d.get("market_cap"),
                "operating_margin": d.get("operating_margin"),
            }
        )
    rows.sort(key=lambda x: (-x["score"], x["ticker"]))
    return rows


def _group_by_sector(matches: list):
    groups = OrderedDict()
    for m in matches:
        sec = m.get("sector") or "미분류"
        groups.setdefault(sec, []).append(m)
    for sec in groups:
        groups[sec].sort(key=lambda x: (-x.get("score", 0), x.get("ticker", "")))
    return OrderedDict(sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True))


def sector_score_table_from_matches(
    matches: list,
    universe_by_sector: dict[str, int] | None = None,
    *,
    total_universe_n: int | None = None,
) -> list:
    """섹터별 Stage2 종목 수·점수 요약. 주도%(presence_pct) 분모 = 선정 후보 전체 종목 수."""
    buckets: dict[str, list[float]] = {}
    for m in matches:
        sec = (m.get("sector") or "미분류").strip() or "미분류"
        buckets.setdefault(sec, []).append(float(m.get("score") or 0))
    uni = universe_by_sector or {}
    tot_all = max(0, int(total_universe_n or 0))
    rows = []
    for sec, scores in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        u = int(uni.get(sec) or 0)
        cnt = len(scores)
        presence = round(100.0 * cnt / tot_all, 2) if tot_all > 0 else None
        rows.append(
            {
                "sector": sec,
                "count": cnt,
                "universe_n": u,
                "universe_total": tot_all,
                "presence_pct": presence,
                "avg_score": round(sum(scores) / len(scores), 2),
                "max_score": round(max(scores), 2),
            }
        )
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


def sector_blocks_charts_only(matches: list) -> list:
    charts = [m for m in matches if m.get("chart")]
    by_sector = _group_by_sector(charts)
    return [{"sector": sec, "entries": items} for sec, items in by_sector.items()]


def _env_flag(name: str, default_on: bool = True) -> bool:
    v = os.environ.get(name, "1" if default_on else "0")
    v = (v or "").strip().lower()
    if default_on:
        return v not in ("0", "false", "no", "off")
    return v in ("1", "true", "yes", "on")


def _fetch_ticker_fundamentals(ticker: str) -> tuple[float | None, float | None]:
    """시가총액(원), TTM 영업이익률(0~1, yfinance). 실패 시 (None, None)."""
    try:
        t = yf.Ticker(ticker)
        mcap: float | None = None
        if hasattr(t, "fast_info"):
            try:
                fi = t.fast_info
                if isinstance(fi, dict):
                    mcap = fi.get("marketCap") or fi.get("market_cap")
            except Exception:
                pass
        inf = t.info
        if mcap is None:
            mcap = inf.get("marketCap") or inf.get("totalMarketCap")
        if mcap is not None:
            mcap = float(mcap)
        o = inf.get("operatingMargins")
        opm: float | None = None
        if o is not None and isinstance(o, (int, float)) and not (isinstance(o, float) and pd.isna(o)):
            opm = float(o)
        return (mcap, opm)
    except Exception:
        return (None, None)


def _rank_linear_bonuses(
    tickers: list[str],
    value_by_ticker: dict[str, float | None],
    max_pts: float,
    *,
    require_positive: bool,
) -> dict[str, float]:
    if max_pts <= 0:
        return {t: 0.0 for t in tickers}

    def ok(v) -> bool:
        if v is None:
            return False
        if not isinstance(v, (int, float)) or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return False
        if require_positive and v <= 0:
            return False
        return True

    valid = [(t, value_by_ticker.get(t)) for t in tickers]
    valid = [(t, v) for t, v in valid if ok(v)]
    if not valid:
        return {t: 0.0 for t in tickers}
    out0 = {t: 0.0 for t in tickers}
    if len(valid) == 1:
        out0[valid[0][0]] = max_pts
        return out0
    sorted_v = sorted(valid, key=lambda x: x[1], reverse=True)
    n = len(sorted_v)
    for i, (t, _) in enumerate(sorted_v):
        br = 1.0 - (i / (n - 1))
        out0[t] = round(max_pts * br, 2)
    return out0


def _apply_fundamental_bonuses_kosdaq(new_matches: dict[str, dict]) -> None:
    """이번 2단계 집합 안에서 시총·영업이익률 순으로 가점(기본: 각 최대 15). 총점에 합산."""
    if not new_matches:
        return
    use_m = _env_flag("KOSDAQ_BONUS_MARKET_CAP", default_on=True)
    use_o = _env_flag("KOSDAQ_BONUS_OPERATING_MARGIN", default_on=True)
    try:
        max_m = float(os.environ.get("KOSDAQ_BONUS_MCAP_PTS", "15") or 15)
    except ValueError:
        max_m = 15.0
    try:
        max_o = float(os.environ.get("KOSDAQ_BONUS_OPM_PTS", "15") or 15)
    except ValueError:
        max_o = 15.0

    tickers = list(new_matches.keys())
    m_map = {t: (new_matches[t].get("market_cap")) for t in tickers}
    o_map = {t: (new_matches[t].get("operating_margin")) for t in tickers}
    m_bon = _rank_linear_bonuses(tickers, m_map, max_m, require_positive=True) if use_m else {t: 0.0 for t in tickers}
    o_bon = _rank_linear_bonuses(tickers, o_map, max_o, require_positive=False) if use_o else {t: 0.0 for t in tickers}

    for t in tickers:
        m = new_matches[t]
        add = m_bon.get(t, 0.0) + o_bon.get(t, 0.0)
        m["score"] = round(float(m.get("score") or 0.0) + add, 2)
        sb = dict(m.get("score_breakdown") or {})
        sb["mcap"] = round(m_bon.get(t, 0.0), 2) if use_m else 0.0
        sb["opm"] = round(o_bon.get(t, 0.0), 2) if use_o else 0.0
        m["score_breakdown"] = sb


def _volume_20_vs_prior20(volume: pd.Series) -> float | None:
    if volume is None or len(volume) < 40:
        return None
    a = float(volume.iloc[-20:].mean())
    b = float(volume.iloc[-40:-20].mean())
    if b <= 0 or pd.isna(a) or pd.isna(b):
        return None
    return a / b


def _volume_strength_vs_benchmark(
    stock_volume: pd.Series, bench_volume: pd.Series | None
) -> float | None:
    """(종목 20d/20d 거래량 비) / (지수 20d/20d 거래량 비). local/analysis_core와 동일."""
    if bench_volume is None or bench_volume.empty or stock_volume is None or len(stock_volume) < 40:
        return None
    aligned = bench_volume.reindex(stock_volume.index).ffill()
    s = _volume_20_vs_prior20(stock_volume)
    b = _volume_20_vs_prior20(aligned)
    if s is None or b is None or b <= 0 or pd.isna(s):
        return None
    return float(s) / float(b)


def score_stage2_components(
    bars_since_stage2_entry: int,
    rs_ratio: float | None,
    vol_5_vs_20: float | None,
    vol_20_vs_prev20: float | None,
    vol_vs_bench_ratio: float | None = None,
    *,
    rs_floor: float | None = None,
    rs_slope: float | None = None,
) -> tuple[float, dict]:
    """
    local/analysis_core.score_stage2_components 와 동일.
    진입 직후(recency 높음)일수록 가점, 오래될수록 감소.

    `rs_floor` / `rs_slope`: Mansfield RS 등에서 63일 RS와 스케일이 다를 때 오버라이드.
    """
    m_rec = float(os.environ.get("SCORE_MAX_RECENCY", "32"))
    m_rs = float(os.environ.get("SCORE_MAX_RS", "40"))
    m_vi = float(os.environ.get("SCORE_MAX_VOL_INTERNAL", "22"))
    m_vb = float(os.environ.get("SCORE_MAX_VOL_VS_BENCH", "18"))
    rcap = float(os.environ.get("SCORE_RECENCY_CAP_BARS", "120"))
    rs_fl = float(rs_floor) if rs_floor is not None else float(os.environ.get("SCORE_RS_FLOOR", "0.92"))
    rs_sl = float(rs_slope) if rs_slope is not None else 90.0
    vb0 = float(os.environ.get("SCORE_VOL_VS_BENCH_NEUTRAL", "1.0"))

    d = max(0, int(bars_since_stage2_entry))
    recency = m_rec * (1.0 - _clamp(d / rcap, 0.0, 1.0))

    if rs_ratio is None:
        rs_pts = 0.0
    else:
        rs_pts = _clamp((float(rs_ratio) - rs_fl) * rs_sl, 0.0, m_rs)
        # RS가 충분히 강한(기본 0.95+) 종목은 최소 RS 점수 바닥을 보장
        rs_strong_ratio = float(os.environ.get("SCORE_RS_STRONG_RATIO", "0.95"))
        rs_strong_min = float(os.environ.get("SCORE_RS_STRONG_MIN_PTS", "45"))
        if float(rs_ratio) >= rs_strong_ratio:
            rs_pts = max(rs_pts, min(rs_strong_min, m_rs))

    v52 = float(vol_5_vs_20) if vol_5_vs_20 is not None else 1.0
    v20 = float(vol_20_vs_prev20) if vol_20_vs_prev20 is not None else 1.0
    cap52 = m_vi * 0.55
    cap20 = m_vi * 0.45
    p52 = _clamp((v52 - 1.0) * 22.0, 0.0, cap52)
    p20 = _clamp((v20 - 1.0) * 32.0, 0.0, cap20)
    vol_internal = _clamp(p52 + p20, 0.0, m_vi)

    if vol_vs_bench_ratio is None:
        vol_bench_pts = 0.0
    else:
        diff = float(vol_vs_bench_ratio) - vb0
        if diff <= 0:
            vol_bench_pts = 0.0
        else:
            vol_bench_pts = _clamp(diff * (m_vb / 0.25), 0.0, m_vb)

    # 총점은 100점 만점으로 정규화
    max_total = max(1e-9, m_rec + m_rs + m_vi + m_vb)
    norm = 100.0 / max_total
    recency_n = recency * norm
    rs_pts_n = rs_pts * norm
    vol_internal_n = vol_internal * norm
    vol_bench_pts_n = vol_bench_pts * norm
    vol_total = round(vol_internal_n + vol_bench_pts_n, 2)
    total = round(recency_n + rs_pts_n + vol_total, 2)
    breakdown = {
        "recency": round(recency_n, 2),
        "rs": round(rs_pts_n, 2),
        "volume": vol_total,
        "volume_internal": round(vol_internal_n, 2),
        "volume_vs_bench": round(vol_bench_pts_n, 2),
        "bars_since_stage2_entry": d,
    }
    return total, breakdown


def _kosdaq_match_from_ohlcv_df(
    df: pd.DataFrame,
    bench_close: pd.Series | None,
    bench_volume: pd.Series | None,
    ticker: str,
    name: str,
    *,
    market_cap: float | None,
    operating_margin: float | None,
) -> dict | None:
    try:
        if df is None or df.empty or len(df) < 250 or "Close" not in df.columns:
            return None
        df = df.copy()
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA50"] = df["Close"].rolling(50).mean()
        df["MA150"] = df["Close"].rolling(150).mean()
        df["MA200"] = df["Close"].rolling(200).mean()
        df["MA200_Trend"] = df["MA200"] > df["MA200"].shift(20)
        stage2_zone = (df["Close"] > df["MA150"]) & (df["MA150"] > df["MA200"]) & (df["MA200_Trend"])
        ma50_up = df["MA50"].iloc[-1] > df["MA50"].iloc[-10]
        price_above_ma50 = df["Close"].iloc[-1] > df["MA50"].iloc[-1]
        if not (bool(stage2_zone.iloc[-1]) and ma50_up and price_above_ma50):
            return None

        ep_idx = stage2_episode_start_index(stage2_zone)
        if ep_idx is None:
            return None
        last_i = len(df) - 1
        bars_since = last_i - ep_idx
        entry_ts = df.index[ep_idx]
        entry_date_str = str(entry_ts.date()) if hasattr(entry_ts, "date") else str(entry_ts)

        if "Volume" in df.columns:
            df["Vol_MA20"] = df["Volume"].rolling(20).mean()
            df["Vol_MA5"] = df["Volume"].rolling(5).mean()
        rs_ratio, rs_fl, rs_sl, rs_extra = resolve_rs_for_score(df["Close"], bench_close, market="kosdaq")
        vol_20 = _volume_20_vs_prior20(df["Volume"] if "Volume" in df.columns else None)
        vma5 = vma20 = None
        if "Volume" in df.columns and "Vol_MA5" in df.columns and "Vol_MA20" in df.columns:
            vma5, vma20 = df["Vol_MA5"].iloc[-1], df["Vol_MA20"].iloc[-1]
        vol_5_vs_20 = (
            float(vma5 / vma20)
            if vma20 and vma20 > 0 and not pd.isna(vma20) and vma5 is not None
            else None
        )
        vol_vs_bench_ratio = _volume_strength_vs_benchmark(
            df["Volume"] if "Volume" in df.columns else None, bench_volume
        )

        try:
            ret_3m = (df["Close"].iloc[-1] / df["Close"].iloc[-60]) - 1.0
        except Exception:
            ret_3m = 0.0
        try:
            entry_c = float(df["Close"].iloc[ep_idx])
            last_c = float(df["Close"].iloc[-1])
            ret_since_entry_pct = (
                ((last_c / entry_c) - 1.0) * 100.0 if entry_c and entry_c > 0 else 0.0
            )
        except Exception:
            ret_since_entry_pct = 0.0
            entry_c = None
            last_c = None

        # 전략별(단타/스윙) 가상 진입 시점 수익률
        day_entry_idx = max(ep_idx, last_i - 3)
        sw_entry_idx = max(ep_idx, last_i - 20)
        day_entry_ts = df.index[day_entry_idx]
        sw_entry_ts = df.index[sw_entry_idx]
        day_entry_date = str(day_entry_ts.date()) if hasattr(day_entry_ts, "date") else str(day_entry_ts)
        sw_entry_date = str(sw_entry_ts.date()) if hasattr(sw_entry_ts, "date") else str(sw_entry_ts)
        try:
            day_entry_c = float(df["Close"].iloc[day_entry_idx])
            ret_daytrade_pct = ((last_c / day_entry_c) - 1.0) * 100.0 if (last_c and day_entry_c > 0) else 0.0
        except Exception:
            ret_daytrade_pct = None
        try:
            sw_entry_c = float(df["Close"].iloc[sw_entry_idx])
            ret_swing_pct = ((last_c / sw_entry_c) - 1.0) * 100.0 if (last_c and sw_entry_c > 0) else 0.0
        except Exception:
            ret_swing_pct = None

        ma20_v = _safe_float(df["MA20"].iloc[-1]) if "MA20" in df.columns else None
        ma50_v = _safe_float(df["MA50"].iloc[-1]) if "MA50" in df.columns else None
        close_v = _safe_float(df["Close"].iloc[-1])
        dist_ma20_pct = (
            _safe_float(((float(close_v) / float(ma20_v)) - 1.0) * 100.0)
            if close_v is not None and ma20_v is not None and float(ma20_v) != 0.0
            else None
        )
        dist_ma50_pct = (
            _safe_float(((float(close_v) / float(ma50_v)) - 1.0) * 100.0)
            if close_v is not None and ma50_v is not None and float(ma50_v) != 0.0
            else None
        )
        stage2_status = (
            "초기·과열"
            if (int(bars_since) <= 20 and ((dist_ma20_pct is not None and dist_ma20_pct >= 20.0) or (dist_ma50_pct is not None and dist_ma50_pct >= 30.0)))
            else "초기·비과열"
            if int(bars_since) <= 20
            else "일반"
        )

        score, score_breakdown = score_stage2_components(
            int(bars_since),
            rs_ratio,
            vol_5_vs_20,
            vol_20,
            vol_vs_bench_ratio,
            rs_floor=rs_fl,
            rs_slope=rs_sl,
        )
        score_breakdown = {**score_breakdown, "mcap": 0.0, "opm": 0.0}

        out_rs: dict[str, Any] = {"rs_ratio": _safe_float(rs_ratio)}
        for _k, _v in rs_extra.items():
            if _k == "rs_model":
                out_rs[_k] = str(_v)
            else:
                out_rs[_k] = _safe_float(_v) if _v is not None else None

        display_name = (CANDIDATES.get(ticker) or [name, ""])[0]
        return {
            "df": df,
            "entry": entry_date_str,
            "bars_since_stage2_entry": int(bars_since),
            **out_rs,
            "ret_since_entry_pct": _safe_float(ret_since_entry_pct) or 0.0,
            "ret_daytrade_pct": _safe_float(ret_daytrade_pct),
            "ret_swing_pct": _safe_float(ret_swing_pct),
            "entry_daytrade": day_entry_date,
            "entry_swing": sw_entry_date,
            "ret_3m_pct": _safe_float(ret_3m * 100.0) or 0.0,
            "close": close_v,
            "ma20": ma20_v,
            "ma50": ma50_v,
            "dist_ma20_pct": dist_ma20_pct,
            "dist_ma50_pct": dist_ma50_pct,
            "stage2_status": stage2_status,
            "vol_5_vs_20": _safe_float(vol_5_vs_20),
            "vol_20_vs_prev20": _safe_float(vol_20),
            "vol_vs_bench_ratio": _safe_float(vol_vs_bench_ratio),
            "score": score,
            "score_breakdown": score_breakdown,
            "market_cap": market_cap,
            "operating_margin": operating_margin,
            "stage2_zone": stage2_zone,
            "name": display_name,
            "display_name": display_name,
        }
    except Exception:
        return None


def _compute_kosdaq_match(
    ticker: str,
    name: str,
    bench_close: pd.Series | None,
    bench_volume: pd.Series | None,
) -> dict | None:
    """Stage2: MA200 우상 + Close>MA150>MA200, 당일 MA50 상승·주가>MA50 (기존 kosdaq app과 동일)."""

    try:
        data = yf.download(ticker, period="2y", interval="1d", progress=False, auto_adjust=True)
        if data.empty or len(data) < 250:
            return None
        df = _normalize_df_columns(data.copy())
        mcap, opm = _fetch_ticker_fundamentals(ticker)
        return _kosdaq_match_from_ohlcv_df(
            df, bench_close, bench_volume, ticker, name, market_cap=mcap, operating_margin=opm
        )
    except Exception:
        return None


_KOSDAQ_ASOF_MIN_ROWS = 250


def _matches_at_asof_kosdaq(
    stock_dfs: dict[str, pd.DataFrame],
    bench_df: pd.DataFrame | None,
    asof: datetime.date,
    fund_map: dict[str, tuple[float | None, float | None]],
) -> dict[str, dict]:
    if bench_df is None or "Close" not in bench_df.columns:
        return {}
    bc = _slice_series_to_asof(bench_df["Close"], asof)
    bv = _slice_series_to_asof(bench_df["Volume"], asof) if "Volume" in bench_df.columns else None
    matches: dict[str, dict] = {}
    for ticker, fulldf in stock_dfs.items():
        dfa = _slice_ohlcv_to_asof(fulldf, asof, min_rows=_KOSDAQ_ASOF_MIN_ROWS)
        if dfa is None:
            continue
        name = CANDIDATES[ticker][0]
        mc, om = fund_map.get(ticker, (None, None))
        m = _kosdaq_match_from_ohlcv_df(dfa, bc, bv, ticker, name, market_cap=mc, operating_margin=om)
        if not m:
            continue
        m.pop("df", None)
        m.pop("stage2_zone", None)
        m.pop("name", None)
        matches[ticker] = {**m, "chart": None}
    if not matches:
        return {}
    _apply_fundamental_bonuses_kosdaq(matches)
    for rank, t in enumerate(
        sorted(matches.keys(), key=lambda x: matches[x]["score"], reverse=True), start=1
    ):
        matches[t]["rank"] = rank
    return matches


def _sector_rank_snap_map_kosdaq(matches: dict[str, dict]) -> dict[str, int]:
    if not matches:
        return {}
    rows = _match_rows_from_detail(matches)
    uni = _universe_counts_by_sector()
    table = sector_score_table_from_matches(rows, uni, total_universe_n=len(CANDIDATES))
    return {str(r["sector"]): int(r["rank"]) for r in table}


def _write_chart(
    df: pd.DataFrame,
    stage2_zone: pd.Series,
    ticker: str,
    name: str,
    path: str,
) -> bool:
    try:
        display_name = (CANDIDATES.get(ticker) or [name, ""])[0]
        fig = plt.figure(figsize=(10, 4))
        plt.fill_between(
            df.index,
            df["Close"].min() * 0.9,
            df["Close"].max() * 1.1,
            where=stage2_zone,
            color="#E3F2FD",
            alpha=0.7,
            label="Stage 2 Zone",
        )
        plt.plot(df.index[-250:], df["Close"][-250:], color="#1A1A1A", lw=1.2, label="Price")
        plt.plot(df.index[-250:], df["MA50"][-250:], color="#2196F3", lw=1.5, ls="--", label="50MA")
        plt.plot(df.index[-250:], df["MA200"][-250:], color="#F44336", lw=2, label="200MA")
        plt.title(f"KOSDAQ STAGE 2: {display_name} ({ticker})", fontsize=12, fontweight="bold")
        plt.xlim(df.index[-250], df.index[-1])
        plt.ylim(df["Close"][-250:].min() * 0.95, df["Close"][-250:].max() * 1.05)
        plt.legend(loc="upper left", fontsize="small", frameon=True)
        plt.grid(True, linestyle=":", alpha=0.4)
        plt.tight_layout()
        plt.savefig(path, dpi=120)
        plt.close(fig)
        return True
    except Exception:
        try:
            plt.close("all")
        except Exception:
            pass
        return False


def run_kosdaq_export(base_dir: str) -> dict:
    """
    base_dir 아래에 charts/, state/, results_web.json 생성.
    """
    charts_dir = os.path.join(base_dir, "charts")
    state_dir = os.path.join(base_dir, "state")
    os.makedirs(charts_dir, exist_ok=True)
    os.makedirs(state_dir, exist_ok=True)
    _setup_font(base_dir)

    signal_history_path = os.path.join(state_dir, "last_run_signals.json")

    # 웹 요약표 행 수(TOP_SUMMARY_ROWS)·추세 PNG 상위 종목(MAX_TREND_CHARTS) 기본 동일(미설정 시 50)
    _default_visible_stocks = 50
    chart_limit_raw = os.environ.get("MAX_TREND_CHARTS", str(_default_visible_stocks)).strip()
    chart_limit = _default_visible_stocks if chart_limit_raw == "" else int(chart_limit_raw)
    if chart_limit < 0:
        chart_limit = 0

    _syn = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _syn not in sys.path:
        sys.path.insert(0, _syn)
    try:
        from yfinance_cache_repair import try_repair_with_message

        try_repair_with_message()
    except ImportError:
        pass

    bench_df, index_status = _download_bench_kq11_dataframe()

    stock_dfs: dict[str, pd.DataFrame] = {}
    total = len(CANDIDATES)

    print(f"[{datetime.datetime.now()}] KOSDAQ Stage2 스캔 → {base_dir} (후보 {total}개)")

    for idx, (ticker, info) in enumerate(CANDIDATES.items(), start=1):
        trend_path = os.path.join(charts_dir, f"{ticker}_trend.png")
        try:
            data = yf.download(ticker, period="2y", interval="1d", progress=False, auto_adjust=True)
            if data.empty or len(data) < 250:
                if os.path.exists(trend_path):
                    try:
                        os.remove(trend_path)
                    except OSError:
                        pass
                continue
            stock_dfs[ticker] = _normalize_df_columns(data.copy())
        except Exception:
            if os.path.exists(trend_path):
                try:
                    os.remove(trend_path)
                except OSError:
                    pass
        finally:
            sys.stdout.write(f"\r  스캔 {100.0 * idx / total:5.1f}% ({idx}/{total})    ")
            sys.stdout.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()

    fund_map: dict[str, tuple[float | None, float | None]] = {}
    for ticker in stock_dfs:
        fund_map[ticker] = _fetch_ticker_fundamentals(ticker)

    cal_iso = _calendar_today_iso("Asia/Seoul")
    t_cal = datetime.date.fromisoformat(cal_iso)
    last_bar = _last_ohlcv_bar_date(bench_df)
    t0 = min(t_cal, last_bar) if last_bar is not None else t_cal
    today_iso = t0.isoformat()
    asof_schedule = [
        t0,
        t0 - datetime.timedelta(days=1),
        t0 - datetime.timedelta(days=2),
        t0 - datetime.timedelta(days=3),
        t0 - datetime.timedelta(days=6),
    ]

    synthetic_rank_hist: dict[str, dict[str, int]] = {}
    synthetic_sector_hist: dict[str, dict[str, int]] = {}
    for asof in asof_schedule:
        if asof == t0:
            continue
        m_asof = _matches_at_asof_kosdaq(stock_dfs, bench_df, asof, fund_map)
        synthetic_rank_hist[asof.isoformat()] = {
            str(t): int(m_asof[t]["rank"]) for t in m_asof
        }
        synthetic_sector_hist[asof.isoformat()] = _sector_rank_snap_map_kosdaq(m_asof)

    new_matches = _matches_at_asof_kosdaq(stock_dfs, bench_df, t0, fund_map)

    plot_cache: dict[str, tuple] = {}
    if bench_df is not None and "Close" in bench_df.columns:
        bc0 = _slice_series_to_asof(bench_df["Close"], t0)
        bv0 = (
            _slice_series_to_asof(bench_df["Volume"], t0) if "Volume" in bench_df.columns else None
        )
        for t in list(new_matches.keys()):
            dfa = _slice_ohlcv_to_asof(stock_dfs[t], t0, min_rows=_KOSDAQ_ASOF_MIN_ROWS)
            if dfa is None:
                continue
            mc, om = fund_map.get(t, (None, None))
            raw = _kosdaq_match_from_ohlcv_df(
                dfa, bc0, bv0, t, (CANDIDATES.get(t) or [t, ""])[0], market_cap=mc, operating_margin=om
            )
            if raw and raw.get("df") is not None and raw.get("stage2_zone") is not None:
                plot_cache[t] = (raw["df"], raw["stage2_zone"])

    sorted_tickers = sorted(new_matches.keys(), key=lambda tt: new_matches[tt]["score"], reverse=True)

    want_charts: set = set(sorted_tickers) if chart_limit == 0 else set(sorted_tickers[:chart_limit])

    for t in sorted_tickers:
        path = os.path.join(charts_dir, f"{t}_trend.png")
        if t not in want_charts:
            new_matches[t]["chart"] = None
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            continue
        new_matches[t]["chart"] = f"{t}_trend.png"
        df, st_z = plot_cache.get(t, (None, None))
        if df is None:
            continue
        if not _write_chart(df, st_z, t, (CANDIDATES.get(t) or [t, ""])[0], path):
            new_matches[t]["chart"] = None

    for fn in os.listdir(charts_dir):
        if not fn.endswith("_trend.png"):
            continue
        base = fn[: -len("_trend.png")]
        if base not in new_matches or not new_matches[base].get("chart"):
            try:
                os.remove(os.path.join(charts_dir, fn))
            except OSError:
                pass

    last_analysis_time = _now_wallclock_str_kst()
    rank_by_date_path = os.path.join(state_dir, "rank_by_date.json")
    rank_hist = _load_rank_by_date(rank_by_date_path)
    rank_hist_before_today = {k: v for k, v in rank_hist.items() if k != today_iso}
    rank_hist_merged = {**rank_hist_before_today, **synthetic_rank_hist}

    signals_by_date_path = os.path.join(state_dir, "signals_by_date.json")
    diff_daily_log_path = os.path.join(state_dir, "diff_daily_log.json")

    history = _load_signals_by_date(signals_by_date_path)
    history = _migrate_signals_history_from_last_run(history, signal_history_path, today_iso)
    prev_signals, diff_baseline_date = _prev_signals_for_diff(history, today_iso)
    last_diff_added, last_diff_removed = _build_diff_lists(prev_signals, new_matches)

    history[today_iso] = {
        "tickers": _minimal_tickers_for_history(new_matches),
        "saved_at": last_analysis_time,
    }
    _prune_signals_history(history, today_iso)
    _save_signals_by_date(signals_by_date_path, history)

    diff_log = _upsert_daily_diff_log(
        diff_daily_log_path,
        {
            "snapshot_date": today_iso,
            "baseline_date": diff_baseline_date,
            "last_diff_added": last_diff_added,
            "last_diff_removed": last_diff_removed,
        },
    )
    diff_past_days = [e for e in diff_log if e.get("snapshot_date") != today_iso][-15:]

    with open(signal_history_path, "w", encoding="utf-8") as f:
        json.dump(
            {"tickers": new_matches, "saved_at": last_analysis_time},
            f,
            ensure_ascii=False,
            indent=2,
        )

    matches = _match_rows_from_detail(new_matches)
    for i, m in enumerate(matches, 1):
        m["rank"] = int(i)
    sector_rank_by_date_path = os.path.join(state_dir, "sector_rank_by_date.json")
    sector_rank_hist = _load_rank_by_date(sector_rank_by_date_path)
    sector_rank_hist_before_today = {k: v for k, v in sector_rank_hist.items() if k != today_iso}
    sector_rank_merged = {**sector_rank_hist_before_today, **synthetic_sector_hist}
    uni_sec = _universe_counts_by_sector()
    sector_score_table = sector_score_table_from_matches(
        matches, uni_sec, total_universe_n=len(CANDIDATES)
    )
    sector_rank_delta_meta = attach_sector_rank_deltas(
        sector_score_table, sector_rank_merged, today_iso
    )
    sector_rank_hist[today_iso] = {
        str(r["sector"]): int(r["rank"]) for r in sector_score_table
    }
    for _d, _mp in synthetic_sector_hist.items():
        if _mp:
            sector_rank_hist[_d] = dict(_mp)
    _prune_rank_by_date(sector_rank_hist, today_iso)
    _save_rank_by_date(sector_rank_by_date_path, sector_rank_hist)
    sector_summary = [(r["sector"], r["count"]) for r in sector_score_table]
    _default_summary = _default_visible_stocks
    summary_table_rows = int(
        (os.environ.get("TOP_SUMMARY_ROWS", str(_default_summary)).strip() or str(_default_summary))
    )
    summary_table_rows = max(1, summary_table_rows)
    top_table = matches[:summary_table_rows]
    tr = {m.get("ticker"): m.get("rank") for m in matches if m.get("ticker")}
    for r in top_table:
        tid = r.get("ticker")
        if tid and tid in tr:
            r["rank"] = tr[tid]
    rank_delta_meta = attach_rank_deltas_to_rows(top_table, rank_hist_merged, today_iso)

    rank_hist[today_iso] = {str(t): int(new_matches[t]["rank"]) for t in new_matches}
    for _d, _mp in synthetic_rank_hist.items():
        if _mp:
            rank_hist[_d] = dict(_mp)
    _prune_rank_by_date(rank_hist, today_iso)
    _save_rank_by_date(rank_by_date_path, rank_hist)

    sector_blocks = sector_blocks_charts_only(matches)

    payload = {
        "last_analysis_time": last_analysis_time,
        "index": index_status,
        "candidate_count": len(CANDIDATES),
        "matches": matches,
        "sector_blocks": sector_blocks,
        "sector_summary": sector_summary,
        "sector_score_table": sector_score_table,
        "top_table": top_table,
        "last_diff_added": last_diff_added,
        "last_diff_removed": last_diff_removed,
        "diff_snapshot_date": today_iso,
        "diff_baseline_date": diff_baseline_date,
        "diff_past_days": diff_past_days,
        "rank_delta_meta": rank_delta_meta,
        "sector_rank_delta_meta": sector_rank_delta_meta,
        "scoring": {
            "description": "코스닥 섹터 고정 루트. 2단계: 주가>MA150>MA200, MA200 20일 우상, 당일 MA50 상승·종가>MA50. 거래량·Vol/지수는 Yahoo(^KQ11) OHLCV만 사용. RS 기본: Mansfield식 주간 RS/직전 52주 평균(KOSDAQ_RS_MODE=mansfield, 폴백 시 63일 legacy). 총점=최근진입+RS+거래량+Vol/지수+시총·영업 가점(KOSDAQ_BONUS_*).",
            "max_trend_charts": chart_limit,
            "summary_table_rows": summary_table_rows,
            "rank_delta_note": "Δ순위: 같은 실행에서 as-of(어제·이틀·3일·6일 전)까지 자른 OHLCV로 재판정한 순위와 비교. 파일 이력은 보조·백업용.",
            "sector_rank_delta_note": "섹터 Δ: 해당 섹터가 'Stage2 종목 수' 기준 섹터 랭킹에서 얼마나 올랐/내렸는지(종목 순위와 동일 규칙). 주도% = (섹터 Stage2 수)÷(선정 후보 전체 종목 수)×100.",
        },
    }

    results_path = os.path.join(base_dir, "results_web.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[{last_analysis_time}] 완료: 2단계 {len(new_matches)}개 → {results_path}")
    _bd = diff_baseline_date or "(저장 이력 없음)"
    print(f"  신규/탈락 ({_bd} → {today_iso}): {len(last_diff_added)} / {len(last_diff_removed)}")
    return payload
