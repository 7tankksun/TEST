"""
코스닥 고정 루트 Stage2 스캔 → NAS 동기화용 results_web.json + charts/ + state/
(로컬 run_local_export.py에서만 실행 권장. NAS는 app_nas_serve_kosdaq가 JSON만 읽음)
state/rank_by_date.json에 일별 순위 스냅샷을 쌓아 상단 요약 표에 Δ1·3·6일 순위 변화를 표시합니다.
"""

from __future__ import annotations

import json
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

import pandas as pd
import yfinance as yf
import matplotlib

matplotlib.use("Agg")
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*Glyph.*", category=UserWarning)
warnings.filterwarnings("ignore", module="matplotlib")

import matplotlib.pyplot as plt

from kosdaq_candidates import CANDIDATES


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


def _normalize_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        except Exception:
            pass
    return df


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


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _index_stage2_status_from_ohlcv_df(
    df: pd.DataFrame, index_ticker: str, display_name: str
) -> dict:
    """
    지수(개별주와 동일) 2단계. 스윙/와인슈타인: 시장 2단계가 우선.
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
    c = dfn["Close"]
    dfn["MA50"] = c.rolling(50).mean()
    dfn["MA150"] = c.rolling(150).mean()
    dfn["MA200"] = c.rolling(200).mean()
    dfn["MA200_Trend"] = dfn["MA200"] > dfn["MA200"].shift(20)
    stage2_zone = (c > dfn["MA150"]) & (dfn["MA150"] > dfn["MA200"]) & (dfn["MA200_Trend"])
    ma50_up = dfn["MA50"].iloc[-1] > dfn["MA50"].iloc[-10]
    price_above_ma50 = c.iloc[-1] > dfn["MA50"].iloc[-1]
    is_s2 = bool(stage2_zone.iloc[-1]) and bool(ma50_up) and bool(price_above_ma50)

    last = float(c.iloc[-1])
    m50 = float(dfn["MA50"].iloc[-1])
    m200 = float(dfn["MA200"].iloc[-1])
    ts = dfn.index[-1]
    as_of = str(ts.date()) if hasattr(ts, "date") else str(ts)

    if is_s2:
        headline = f"{display_name} ({index_ticker}): 2단계 상승 — 시장이 스테이지2 (포지션·진입에 유리)"
        tone = "stage2"
    elif last < m200:
        headline = f"{display_name} ({index_ticker}): 2단계 아님 — 약세(종가<MA200), 상승 투자엔 경계"
        tone = "bear"
    elif last < m50:
        headline = f"{display_name} ({index_ticker}): 2단계 아님 — 단기 둔화(종가<MA50)"
        tone = "caution"
    else:
        headline = f"{display_name} ({index_ticker}): 2단계 아님 — 조정·눌림/횡보 등(지수 2단계 조건 미충족)"
        tone = "weak"

    return {
        "ticker": index_ticker,
        "name": display_name,
        "is_stage2": is_s2,
        "headline": headline,
        "tone": tone,
        "as_of": as_of,
        "last_close": round(last, 2),
        "ma50": round(m50, 2),
        "ma200": round(m200, 2),
    }


def _load_bench_kq11() -> tuple[pd.Series | None, pd.Series | None, dict]:
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
            return None, None, fail_status
        df = _normalize_df_columns(data.copy())
        status = _index_stage2_status_from_ohlcv_df(df, "^KQ11", "코스닥")
        if "Close" not in df.columns:
            return None, None, status
        vol = df["Volume"] if "Volume" in df.columns else None
        if len(df) < 200:
            return df["Close"], vol, status
        return df["Close"], vol, status
    except Exception:
        return None, None, {
            **fail_status,
            "headline": "코스닥 지수: 조회 실패",
        }


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


def _prev_signals_strictly_before_date(history: dict, today_iso: str) -> tuple[dict, str | None]:
    prior = [d for d in history.keys() if isinstance(d, str) and len(d) == 10 and d < today_iso]
    if not prior:
        return {}, None
    bd = max(prior)
    raw = (history.get(bd) or {}).get("tickers") or {}
    return {k: _normalize_signal_value(v) for k, v in raw.items()}, bd


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


def _best_rank_snapshot_on_or_before(rank_hist: dict, cutoff_iso: str) -> tuple[str | None, dict[str, int]]:
    """cutoff_iso 이전(포함) 날짜 중 가장 최근 저장분의 ticker→순위."""

    dates = [d for d in rank_hist.keys() if isinstance(d, str) and len(d) == 10 and d <= cutoff_iso]
    if not dates:
        return None, {}
    dmax = max(dates)
    raw = rank_hist.get(dmax) or {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        ks = str(k)
        try:
            out[ks] = int(v)
        except (TypeError, ValueError):
            continue
    return dmax, out


def _fmt_rank_delta(prev_rank: int | None, curr_rank: int | None) -> str:
    """이전 순위 대비 변화 (+숫자=순위 상승, 음수=하락). 데이터 없으면 —."""

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


def _attach_rank_deltas_to_rows(
    rows: list,
    rank_hist_before_today: dict,
    today_iso: str,
) -> dict[str, str | None]:
    """각 행에 rank_delta_1d / 3d / 6d 문자열 부여. 참조 스냅샷 일자 메타 반환."""

    meta: dict[str, str | None] = {}
    for r in rows:
        r["rank_delta_1d"] = "—"
        r["rank_delta_3d"] = "—"
        r["rank_delta_6d"] = "—"

    try:
        t0 = datetime.date.fromisoformat(today_iso)
    except ValueError:
        return meta

    offsets = (("1d", 1), ("3d", 3), ("6d", 6))
    snaps: dict[str, tuple[str | None, dict[str, int]]] = {}
    for label, days in offsets:
        cutoff = (t0 - datetime.timedelta(days=days)).isoformat()
        d_snap, mp = _best_rank_snapshot_on_or_before(rank_hist_before_today, cutoff)
        snaps[label] = (d_snap, mp)
        meta[f"snapshot_{label}"] = d_snap

    for r in rows:
        tid = str(r.get("ticker") or "")
        try:
            cr = int(r.get("rank"))
        except (TypeError, ValueError):
            cr = None
        for label, _days in offsets:
            _, mp = snaps[label]
            pr = mp.get(tid) if mp and tid else None
            r[f"rank_delta_{label}"] = _fmt_rank_delta(pr, cr)

    return meta


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
        rows.append(
            {
                "ticker": t,
                "name": CANDIDATES[t][0],
                "entry": d["entry"],
                "chart": d.get("chart"),
                "sector": get_sector(t),
                "rank": d["rank"],
                "score": d["score"],
                "score_breakdown": d.get("score_breakdown") or {},
                "bars_since_stage2_entry": d.get("bars_since_stage2_entry"),
                "rs_ratio": d.get("rs_ratio"),
                "ret_3m_pct": d.get("ret_3m_pct"),
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


def sector_score_table_from_matches(matches: list) -> list:
    buckets: dict[str, list[float]] = {}
    for m in matches:
        sec = (m.get("sector") or "미분류").strip() or "미분류"
        buckets.setdefault(sec, []).append(float(m.get("score") or 0))
    rows = []
    for sec, scores in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        rows.append(
            {
                "sector": sec,
                "count": len(scores),
                "avg_score": round(sum(scores) / len(scores), 2),
                "max_score": round(max(scores), 2),
            }
        )
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
) -> tuple[float, dict]:
    """
    local/analysis_core.score_stage2_components 와 동일.
    진입 직후(recency 높음)일수록 가점, 오래될수록 감소.
    """
    m_rec = float(os.environ.get("SCORE_MAX_RECENCY", "32"))
    m_rs = float(os.environ.get("SCORE_MAX_RS", "40"))
    m_vi = float(os.environ.get("SCORE_MAX_VOL_INTERNAL", "22"))
    m_vb = float(os.environ.get("SCORE_MAX_VOL_VS_BENCH", "18"))
    rcap = float(os.environ.get("SCORE_RECENCY_CAP_BARS", "120"))
    rs_floor = float(os.environ.get("SCORE_RS_FLOOR", "0.92"))
    vb0 = float(os.environ.get("SCORE_VOL_VS_BENCH_NEUTRAL", "1.0"))

    d = max(0, int(bars_since_stage2_entry))
    recency = m_rec * (1.0 - _clamp(d / rcap, 0.0, 1.0))

    if rs_ratio is None:
        rs_pts = 0.0
    else:
        rs_pts = _clamp((float(rs_ratio) - rs_floor) * 90.0, 0.0, m_rs)

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

    vol_total = round(vol_internal + vol_bench_pts, 2)
    total = round(recency + rs_pts + vol_total, 2)
    breakdown = {
        "recency": round(recency, 2),
        "rs": round(rs_pts, 2),
        "volume": vol_total,
        "volume_internal": round(vol_internal, 2),
        "volume_vs_bench": round(vol_bench_pts, 2),
        "bars_since_stage2_entry": d,
    }
    return total, breakdown


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
        rs_ratio = relative_strength_ratio(df["Close"], bench_close)
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

        score, score_breakdown = score_stage2_components(
            int(bars_since),
            rs_ratio,
            vol_5_vs_20,
            vol_20,
            vol_vs_bench_ratio,
        )
        score_breakdown = {**score_breakdown, "mcap": 0.0, "opm": 0.0}

        mcap, opm = _fetch_ticker_fundamentals(ticker)

        return {
            "df": df,
            "entry": entry_date_str,
            "bars_since_stage2_entry": int(bars_since),
            "rs_ratio": _safe_float(rs_ratio),
            "ret_3m_pct": _safe_float(ret_3m * 100.0) or 0.0,
            "vol_5_vs_20": _safe_float(vol_5_vs_20),
            "vol_20_vs_prev20": _safe_float(vol_20),
            "vol_vs_bench_ratio": _safe_float(vol_vs_bench_ratio),
            "score": score,
            "score_breakdown": score_breakdown,
            "market_cap": mcap,
            "operating_margin": opm,
            "stage2_zone": stage2_zone,
            "name": name,
        }
    except Exception:
        return None


def _write_chart(
    df: pd.DataFrame,
    stage2_zone: pd.Series,
    ticker: str,
    name: str,
    path: str,
) -> bool:
    try:
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
        plt.title(f"KOSDAQ STAGE 2: {name} ({ticker})", fontsize=12, fontweight="bold")
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

    chart_limit_raw = os.environ.get("MAX_TREND_CHARTS", "50").strip()
    chart_limit = 50 if chart_limit_raw == "" else int(chart_limit_raw)
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

    bench_close, bench_volume, index_status = _load_bench_kq11()
    new_matches: dict[str, dict] = {}
    plot_cache: dict[str, tuple] = {}
    total = len(CANDIDATES)

    print(f"[{datetime.datetime.now()}] KOSDAQ Stage2 스캔 → {base_dir} (후보 {total}개)")

    for idx, (ticker, info) in enumerate(CANDIDATES.items(), start=1):
        name = info[0]
        trend_path = os.path.join(charts_dir, f"{ticker}_trend.png")
        try:
            m = _compute_kosdaq_match(ticker, name, bench_close, bench_volume)
            if m is None:
                if os.path.exists(trend_path):
                    try:
                        os.remove(trend_path)
                    except OSError:
                        pass
                continue
            df = m.pop("df")
            st_z = m.pop("stage2_zone")
            m.pop("name", None)
            new_matches[ticker] = {**m, "chart": None, "rank": 0}
            plot_cache[ticker] = (df, st_z)
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

    _apply_fundamental_bonuses_kosdaq(new_matches)

    sorted_tickers = sorted(new_matches.keys(), key=lambda t: new_matches[t]["score"], reverse=True)
    for rank, t in enumerate(sorted_tickers, start=1):
        new_matches[t]["rank"] = rank

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
        if not _write_chart(df, st_z, t, CANDIDATES[t][0], path):
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

    last_analysis_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_iso = _calendar_today_iso("Asia/Seoul")
    rank_by_date_path = os.path.join(state_dir, "rank_by_date.json")
    rank_hist = _load_rank_by_date(rank_by_date_path)
    rank_hist_before_today = {k: v for k, v in rank_hist.items() if k != today_iso}

    signals_by_date_path = os.path.join(state_dir, "signals_by_date.json")
    diff_daily_log_path = os.path.join(state_dir, "diff_daily_log.json")

    history = _load_signals_by_date(signals_by_date_path)
    history = _migrate_signals_history_from_last_run(history, signal_history_path, today_iso)
    prev_signals, diff_baseline_date = _prev_signals_strictly_before_date(history, today_iso)
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
    sector_score_table = sector_score_table_from_matches(matches)
    sector_summary = [(r["sector"], r["count"]) for r in sector_score_table]
    _default_summary = 30
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
    rank_delta_meta = _attach_rank_deltas_to_rows(top_table, rank_hist_before_today, today_iso)

    rank_hist[today_iso] = {str(t): int(new_matches[t]["rank"]) for t in new_matches}
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
        "scoring": {
            "description": "코스닥 섹터 고정 루트. 2단계: 주가>MA150>MA200, MA200 20일 우상, 당일 MA50 상승·종가>MA50. 거래량·Vol/지수는 Yahoo(^KQ11) OHLCV만 사용. 총점=최근진입+RS+거래량+Vol/지수+시총·영업 가점(KOSDAQ_BONUS_*).",
            "max_trend_charts": chart_limit,
            "summary_table_rows": summary_table_rows,
            "rank_delta_note": "Δ순위: 저장된 순위 스냅샷 대비(당일−N일 이전 시점 이전 가장 최근 저장일). +는 순위 상승(숫자 감소 방향).",
        },
    }

    results_path = os.path.join(base_dir, "results_web.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[{last_analysis_time}] 완료: 2단계 {len(new_matches)}개 → {results_path}")
    _bd = diff_baseline_date or "(저장 이력 없음)"
    print(f"  신규/탈락 ({_bd} → {today_iso}): {len(last_diff_added)} / {len(last_diff_removed)}")
    return payload
