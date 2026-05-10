"""
로컬 PC에서만 실행하는 Stage2 분석 + NAS로 복사할 결과물(results_web.json, charts/, state/) 생성.
NAS에서는 이 모듈을 import하지 않는 것을 권장(app_nas_serve만 사용).
"""

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
import matplotlib.font_manager as fm

from candidates_data import CANDIDATES
from rank_delta_utils import attach_rank_deltas_to_rows

_sector_map = None

# 마지막 export 후 메모리 상태 (app_r1 로컬 웹이 읽을 수 있음)
DISPLAY = {
    "signal_times": {},
    "last_analysis_time": None,
    "last_diff_added": [],
    "last_diff_removed": [],
    "matches": [],
    "sector_blocks": [],
    "sector_summary": [],
    "sector_score_table": [],
    "top_table": [],
    "candidate_count": 0,
    "scoring": None,
    "rank_delta_meta": {},
}


def _configure_stdio_utf8() -> None:
    # PowerShell 코드페이지/리다이렉션 환경에서도 한글 로그가 깨지지 않게 보정
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _sector_from_candidate_info(info) -> str:
    """
    candidates_data.py의 2번째 값에서 섹터 추출.
    - '코스피', '코스닥' 접두는 제거
    - '-', '*', '/' 구분자 앞까지만 섹터로 사용
    """
    if not isinstance(info, (list, tuple)) or len(info) < 2:
        return "미분류"
    s = str(info[1] or "").strip()
    if not s:
        return "미분류"
    for prefix in ("코스피", "코스닥", "KOSPI", "KOSDAQ"):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
            if s.startswith("-"):
                s = s[1:].strip()
            break
    # "/"는 업종의 하위분류 표현(예: 철강/강관)으로 자주 쓰여 유지
    for sep in ("-", "*"):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
    return s or "미분류"


def setup_korean_font(font_dir: str):
    font_path = os.path.join(font_dir, "NanumGothic.ttf")
    if os.path.exists(font_path):
        fe = fm.FontEntry(fname=font_path, name="NanumGothic")
        fm.fontManager.ttflist.insert(0, fe)
        plt.rcParams["font.family"] = fe.name
    elif sys.platform == "win32":
        plt.rcParams["font.family"] = "Malgun Gothic"
    else:
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def _load_sector_map():
    global _sector_map
    if _sector_map is not None:
        return _sector_map
    # 1) candidates_data 기준 섹터 우선
    _sector_map = {t: _sector_from_candidate_info(info) for t, info in CANDIDATES.items()}
    try:
        import FinanceDataReader as fdr

        df = fdr.StockListing("KRX")
        market_labels = {"코스피", "코스닥", "KOSPI", "KOSDAQ"}
        for _, r in df.iterrows():
            code = str(r["Code"]).zfill(6)
            mk = str(r.get("Market", ""))
            # 업종 우선: Sector > Industry > Dept (Dept는 코스피/코스닥일 수 있어 후순위)
            sec = str(r.get("Sector", "") or "").strip()
            ind = str(r.get("Industry", "") or "").strip()
            dept = str(r.get("Dept", "") or "").strip()
            candidates = [sec, ind, dept]
            sector_name = "미분류"
            for v in candidates:
                if not v or v.lower() == "nan":
                    continue
                if v in market_labels:
                    continue
                sector_name = v
                break
            if mk == "KOSPI":
                t = f"{code}.KS"
            elif mk == "KOSDAQ":
                t = f"{code}.KQ"
            else:
                continue
            # candidates_data에 유효 섹터가 없을 때만 FDR로 보강
            if _sector_map.get(t, "미분류") in ("", "미분류"):
                _sector_map[t] = sector_name
    except Exception:
        pass
    return _sector_map


def get_sector(ticker):
    t = str(ticker or "").strip()
    base = _load_sector_map().get(t, "미분류")
    if str(base).strip() in ("", "코스피", "코스닥", "KOSPI", "KOSDAQ"):
        base = "미분류"
    info = CANDIDATES.get(t, [])
    name = str(info[0] or "") if isinstance(info, (list, tuple)) and info else ""
    extra = str(info[1] or "") if isinstance(info, (list, tuple)) and len(info) > 1 else ""
    try:
        from surge_sector_resolve import resolve_surge_sector

        return resolve_surge_sector(
            ticker=t, name=name, payload_sector=str(base or "미분류"), extra_hint=extra
        )
    except Exception:
        return base if base and base != "미분류" else "미분류"


def _normalize_df_columns(df):
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        except Exception:
            pass
    return df


def benchmark_symbol_for_ticker(ticker: str) -> str:
    """코스닥은 ^KQ11, 그 외는 ^KS11 기준 상대강도."""
    return "^KQ11" if ticker.endswith(".KQ") else "^KS11"


def load_benchmark_close_series() -> dict[str, dict[str, pd.Series | None] | None]:
    """
    Stage2 스캔 전 한 번만 호출. 키: ^KS11, ^KQ11.
    값: {"close", "volume"} — 거래량 상대강도(지수 대비)에 Volume 사용.
    """
    out: dict[str, dict[str, pd.Series | None] | None] = {}
    for sym in ("^KS11", "^KQ11"):
        try:
            data = yf.download(sym, period="3y", interval="1d", progress=False, auto_adjust=True)
            if data.empty:
                out[sym] = None
            else:
                df = _normalize_df_columns(data.copy())
                vol = df["Volume"] if "Volume" in df.columns else None
                out[sym] = {"close": df["Close"], "volume": vol}
        except Exception:
            out[sym] = None
    return out


def _bench_close_series(bench_entry) -> pd.Series | None:
    if bench_entry is None:
        return None
    if isinstance(bench_entry, dict):
        return bench_entry.get("close")
    return bench_entry


def _bench_volume_series(bench_entry) -> pd.Series | None:
    if bench_entry is None:
        return None
    if isinstance(bench_entry, dict):
        return bench_entry.get("volume")
    return None


def relative_strength_ratio(
    stock_close: pd.Series, bench_close: pd.Series | None, lookback: int = 63
) -> float | None:
    """
    최근 lookback 거래일 구간에서 (종목 누적비율)/(지수 누적비율).
    1.0 이상이면 동기간 코스피/코스닥 대비 상대강도 우위.
    """
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


def volume_20d_vs_prior20(volume: pd.Series) -> float | None:
    """최근 20일 평균 거래량 / 그 직전 20일 평균. 유동성 증가 여부."""
    if volume is None or len(volume) < 40:
        return None
    a = float(volume.iloc[-20:].mean())
    b = float(volume.iloc[-40:-20].mean())
    if b <= 0 or pd.isna(a) or pd.isna(b):
        return None
    return a / b


def volume_strength_vs_benchmark(
    stock_volume: pd.Series, bench_volume: pd.Series | None
) -> float | None:
    """
    (종목 20d/20d 거래량 비) / (동일기준 지수 20d/20d 거래량 비).
    1.0: 지수와 같은 속도로 유동성 증가, >1.0: 지수보다 수급/거래가 더 붙는 편.
    """
    if bench_volume is None or bench_volume.empty or stock_volume is None or len(stock_volume) < 40:
        return None
    aligned = bench_volume.reindex(stock_volume.index).ffill()
    s = volume_20d_vs_prior20(stock_volume)
    b = volume_20d_vs_prior20(aligned)
    if s is None or b is None or b <= 0 or pd.isna(s):
        return None
    return float(s) / float(b)


def stage2_episode_start_index(is_stage2: pd.Series) -> int | None:
    """현재 막대가 Stage2일 때, 이번 연속 True 구간의 시작 행 인덱스(정수)."""
    if is_stage2.empty or not bool(is_stage2.iloc[-1]):
        return None
    i = len(is_stage2) - 1
    while i >= 0 and bool(is_stage2.iloc[i]):
        i -= 1
    return i + 1


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _safe_float(x) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if pd.isna(v):
        return None
    return v


def score_stage2_components(
    bars_since_stage2_entry: int,
    rs_ratio: float | None,
    vol_5_vs_20: float | None,
    vol_20_vs_prev20: float | None,
    vol_vs_bench_ratio: float | None = None,
) -> tuple[float, dict]:
    """
    2단계 보유 종목 랭킹용 (총점은 상한 ~115 근처, 환경변수로 스케일).

    - **recency**: 막 2단계에 올라온 뒤 며칠 지났는지 (초기 추세·진입 맥락)
    - **rs**: **가격** 상대강도(63d 종가 수익률 / 코스피·코스닥 지수) — 우량·주도권 반영
    - **volume**: 종목 **내부** 거래량 모멘텀 (5d/20d, 20d/전20d)
    - **volume_vs_bench**: **거래량** 상대강도 — (종목 20d/20d)÷(지수 20d/20d), 1.0=동일

    환경 변수(기본):
      SCORE_MAX_RECENCY(32) SCORE_MAX_RS(40) SCORE_MAX_VOL_INTERNAL(22) SCORE_MAX_VOL_VS_BENCH(18)
      SCORE_RECENCY_CAP_BARS(120) SCORE_RS_FLOOR(0.92) — 가격 RS 0점 시작선(기존과 동일)
      SCORE_VOL_VS_BENCH_NEUTRAL(1.0) — 거래량 RS(지수 대비) 0점
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
        # 기존: (rs-0.92)*90, 상한 35. 동일 곡률 + 상한만 SCORE_MAX_RS.
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
            # diff≈0.25(비율 1.25)에서 만점에 가깝게
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


def fetch_yf_fundamentals(ticker: str) -> dict:
    """
    yfinance로 시가총액·최신 손익(영업이익, 가능하면 영업이익률).
    한국 섹터는 누락·지연 데이터가 흔해 None이 나올 수 있음.
    """
    out = {"market_cap": None, "operating_income": None, "operating_margin": None}
    try:
        t = yf.Ticker(ticker)
        info = t.info
        if isinstance(info, dict):
            for key in ("marketCap", "enterpriseValue"):
                v = info.get(key)
                if v is not None:
                    try:
                        fv = float(v)
                        if fv > 0:
                            out["market_cap"] = fv
                            break
                    except (TypeError, ValueError):
                        pass
        st = getattr(t, "income_stmt", None)
        if st is None or (hasattr(st, "empty") and st.empty):
            st = getattr(t, "quarterly_income_stmt", None)
        if st is not None and not st.empty and "Operating Income" in st.index:
            oi = _safe_float(st.loc["Operating Income"].iloc[0])
            out["operating_income"] = oi
            rev = None
            for lbl in ("Total Revenue", "Revenue", "Net Revenue"):
                if lbl in st.index:
                    rev = _safe_float(st.loc[lbl].iloc[0])
                    break
            if oi is not None and rev is not None and rev > 0:
                out["operating_margin"] = float(oi) / float(rev)
    except Exception:
        pass
    return out


def _batch_rank_points(
    tickers: list[str],
    values: list[float | None],
    max_pts: float,
    *,
    use_log: bool,
    require_positive: bool = True,
) -> dict[str, float]:
    """
    values가 클수록 점수 높게(상대 순위). None 은 0점.
    use_log: 시총·절대액·영업이익 등 log10 스케일(양수만).
    require_positive: False이면 0/음수도 순위(영업이익률 음수 등).
    """
    pairs: list[tuple[str, float]] = []
    for t, v in zip(tickers, values):
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if pd.isna(x):
            continue
        if require_positive and x <= 0:
            continue
        if use_log:
            if x <= 0:
                continue
            x = math.log10(x)
        pairs.append((t, x))
    n = len(pairs)
    if n == 0:
        return {t: 0.0 for t in tickers}
    pairs.sort(key=lambda p: p[1])
    out = {t: 0.0 for t in tickers}
    for rank, (t, _) in enumerate(pairs):
        out[t] = round(max_pts * (rank / max(n - 1, 1)), 2)
    return out


def _env_enabled(key: str) -> bool:
    return os.environ.get(key, "").strip().lower() in ("1", "true", "yes", "on")


def _fund_score_enabled() -> bool:
    """시총·영업 배치 가점 — 기본 ON, SCORE_FUND_DISABLE=1 이면 OFF."""
    return not _env_enabled("SCORE_FUND_DISABLE")


def apply_fundamental_score_layer(new_matches: dict[str, dict]) -> None:
    """
    이번 스캔에 잡힌 2단계 종목 **끼리만** 시총·영업(이익률 우선) 상대 가점.
    가점은 **가격 RS 점수와 합산**되며, 합계는 SCORE_MAX_RS(기본 40)를 넘지 않습니다.
    (잡주·초소형 시총은 RS 총점이 올라가기 어렵게 설계.)
    기본 적용. 끄려면: SCORE_FUND_DISABLE=1
    """
    if not _fund_score_enabled():
        return
    if not new_matches:
        return
    # 요청 반영: 재무 품질(시총·영업이익률) 가점 비중 상향
    m_mcap = float(os.environ.get("SCORE_FUND_MCAP_MAX", "12"))
    m_oi = float(os.environ.get("SCORE_FUND_OI_MAX", "10"))
    m_rs_cap = float(os.environ.get("SCORE_MAX_RS", "40"))
    tickers = list(new_matches.keys())
    n_f = len(tickers)
    print(
        f"  재무→RS 가점(강화) · {n_f}종 · 시총≤+{m_mcap:.0f} + 영업≤+{m_oi:.0f} "
        f"→ RS상한 {m_rs_cap:.0f}pt"
    )
    raw: dict[str, dict] = {}
    for i, t in enumerate(tickers, 1):
        raw[t] = fetch_yf_fundamentals(t)
        d = new_matches[t]
        d["market_cap"] = _safe_float(raw[t].get("market_cap"))
        d["operating_income"] = _safe_float(raw[t].get("operating_income"))
        d["operating_margin"] = _safe_float(raw[t].get("operating_margin"))
        pct = 100.0 * i / n_f
        sys.stdout.write(f"\r  재무 조회 {pct:5.1f}% ({i}/{n_f})    ")
        sys.stdout.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()
    mcap_v = [raw[t].get("market_cap") for t in tickers]
    mcap_pts = _batch_rank_points(tickers, mcap_v, m_mcap, use_log=True)
    margins = [raw[t].get("operating_margin") for t in tickers]
    oi_abs = [raw[t].get("operating_income") for t in tickers]
    if any(m is not None for m in margins):
        oi_pts = _batch_rank_points(tickers, margins, m_oi, use_log=False, require_positive=False)
    else:
        oi_pts = _batch_rank_points(tickers, oi_abs, m_oi, use_log=True, require_positive=True)
    for t in tickers:
        add_m = mcap_pts.get(t, 0.0)
        add_o = oi_pts.get(t, 0.0)
        d = new_matches[t]
        bd = dict(d.get("score_breakdown") or {})
        rs_price = float(bd.get("rs", 0.0))
        recency = float(bd.get("recency", 0.0))
        vol = float(bd.get("volume", 0.0))
        rs_combined = min(m_rs_cap, rs_price + add_m + add_o)
        bd["rs_price"] = round(rs_price, 2)
        bd["rs_quality_mcap"] = round(add_m, 2)
        bd["rs_quality_op"] = round(add_o, 2)
        bd["rs"] = round(rs_combined, 2)
        d["score"] = round(recency + rs_combined + vol, 2)
        d["score_breakdown"] = bd


def _normalize_signal_value(v):
    """last_run_signals.json: 문자열(구버전) 또는 dict."""
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


def _build_diff_lists(prev_tickers, new_matches):
    prev_keys = set(prev_tickers.keys())
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
        for t in sorted(
            added_keys,
            key=lambda x: (new_matches[x].get("rank") or 9999, x),
        )
    ]
    last_diff_removed = [
        {
            "ticker": t,
            "name": CANDIDATES.get(t, ["?", "?"])[0],
            "entry": prev_tickers[t]["entry"],
            "sector": get_sector(t),
        }
        for t in removed_keys
    ]
    return last_diff_added, last_diff_removed


def _calendar_today_iso(tz_name: str) -> str:
    if ZoneInfo is not None:
        try:
            return datetime.datetime.now(ZoneInfo(tz_name)).date().isoformat()
        except Exception:
            pass
    return datetime.datetime.now().date().isoformat()


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
                "operating_income": d.get("operating_income"),
                "operating_margin": d.get("operating_margin"),
            }
        )
    rows.sort(key=lambda x: (-x["score"], x["ticker"]))
    return rows


def _group_by_sector(matches):
    groups = OrderedDict()
    for m in matches:
        sec = m["sector"] or "미분류"
        groups.setdefault(sec, []).append(m)
    for sec in groups:
        groups[sec].sort(key=lambda x: (-x.get("score", 0), x.get("ticker", "")))
    return OrderedDict(sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True))


def sector_score_table_from_matches(matches: list) -> list:
    """섹터별 2단계 종목 수·평균·최고 총점 (종합 요약 테이블용)."""
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
    """차트가 있는 종목만 섹터별 그룹(상위 N 카드 영역)."""
    charts = [m for m in matches if m.get("chart")]
    by_sector = _group_by_sector(charts)
    return [{"sector": sec, "entries": items} for sec, items in by_sector.items()]


def run_analysis_export(base_dir: str) -> dict:
    """
    base_dir 아래에 charts/, state/, results_web.json 생성.
    반환값은 results_web.json과 동일한 dict.
    """
    global DISPLAY
    _load_sector_map()

    charts_dir = os.path.join(base_dir, "charts")
    state_dir = os.path.join(base_dir, "state")
    font_dir = os.path.join(base_dir, "fonts")
    os.makedirs(charts_dir, exist_ok=True)
    os.makedirs(state_dir, exist_ok=True)
    os.makedirs(font_dir, exist_ok=True)

    setup_korean_font(font_dir)

    signal_history_path = os.path.join(state_dir, "last_run_signals.json")
    prev_signals = _load_previous_signals(signal_history_path)

    _syn = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _syn not in sys.path:
        sys.path.insert(0, _syn)
    try:
        from yfinance_cache_repair import try_repair_with_message

        try_repair_with_message()
    except ImportError:
        pass

    benchmarks = load_benchmark_close_series()
    chart_limit_raw = os.environ.get("MAX_TREND_CHARTS", "50").strip()
    if chart_limit_raw == "":
        chart_limit = 50
    else:
        chart_limit = int(chart_limit_raw)
    if chart_limit < 0:
        chart_limit = 0

    new_matches: dict[str, dict] = {}
    plot_cache: dict[str, pd.DataFrame] = {}
    total = len(CANDIDATES)

    print(f"[{datetime.datetime.now()}] Stage 2 전체 스캔(가점·순위) → 출력: {base_dir} (후보 {total}개)")
    print(
        f"  현재 2단계 종목 전부 수집 | 가점=최근진입+RS(가격+시총·영업)+거래량·Vol/지수"
        f"{' (재무는 RS상한 내)' if _fund_score_enabled() else ''} | 추세차트: 상위 {chart_limit if chart_limit else '전체'}종"
    )
    scan_verbose = _env_enabled("STAGE2_SCAN_VERBOSE")
    for idx, (ticker, info) in enumerate(CANDIDATES.items(), start=1):
        name = info[0]
        trend_path = os.path.join(charts_dir, f"{ticker}_trend.png")
        try:
            data = yf.download(ticker, period="3y", interval="1d", progress=False, auto_adjust=True)
            if data.empty or len(data) < 260:
                if os.path.exists(trend_path):
                    os.remove(trend_path)
                continue

            df = _normalize_df_columns(data.copy())
            df["MA50"] = df["Close"].rolling(50).mean()
            df["MA150"] = df["Close"].rolling(150).mean()
            df["MA200"] = df["Close"].rolling(200).mean()
            df["Vol_MA20"] = df["Volume"].rolling(20).mean()
            df["Vol_MA5"] = df["Volume"].rolling(5).mean()
            df["is_stage2"] = (df["Close"] > df["MA150"]) & (df["MA150"] > df["MA200"])

            is_currently_stage2 = bool(df["is_stage2"].iloc[-1])
            if not is_currently_stage2:
                if os.path.exists(trend_path):
                    os.remove(trend_path)
                continue

            ep_idx = stage2_episode_start_index(df["is_stage2"])
            if ep_idx is None:
                continue
            last_i = len(df) - 1
            bars_since_entry = last_i - ep_idx
            entry_ts = df.index[ep_idx]
            entry_date_str = str(entry_ts.date()) if hasattr(entry_ts, "date") else str(entry_ts)

            three_month_return = (df["Close"].iloc[-1] / df["Close"].iloc[-60]) - 1
            bench_sym = benchmark_symbol_for_ticker(ticker)
            bench_bundle = benchmarks.get(bench_sym)
            rs_ratio = relative_strength_ratio(df["Close"], _bench_close_series(bench_bundle))
            vol_20_vs_prev20 = volume_20d_vs_prior20(df["Volume"])
            vma5, vma20 = df["Vol_MA5"].iloc[-1], df["Vol_MA20"].iloc[-1]
            vol_5_vs_20 = (
                float(vma5 / vma20)
                if vma20 and vma20 > 0 and not pd.isna(vma20)
                else None
            )
            vol_vs_bench_ratio = volume_strength_vs_benchmark(
                df["Volume"], _bench_volume_series(bench_bundle)
            )

            score, breakdown = score_stage2_components(
                bars_since_entry,
                rs_ratio,
                vol_5_vs_20,
                vol_20_vs_prev20,
                vol_vs_bench_ratio,
            )

            new_matches[ticker] = {
                "entry": entry_date_str,
                "bars_since_stage2_entry": int(bars_since_entry),
                "rs_ratio": _safe_float(rs_ratio),
                "ret_3m_pct": _safe_float(three_month_return * 100.0) or 0.0,
                "vol_5_vs_20": _safe_float(vol_5_vs_20),
                "vol_20_vs_prev20": _safe_float(vol_20_vs_prev20),
                "vol_vs_bench_ratio": _safe_float(vol_vs_bench_ratio),
                "score": score,
                "score_breakdown": breakdown,
                "chart": None,
                "rank": 0,
            }
            plot_cache[ticker] = df.copy()
            vb = vol_vs_bench_ratio
            vb_s = f"{vb:.2f}" if vb is not None else "-"
            if scan_verbose:
                print(
                    f"2단계: {name} ({ticker}) 점수 {score} (진입 {entry_date_str}, "
                    f"가격RS {rs_ratio:.2f}, Vol {breakdown['volume']:.1f}, Vol/지수 {vb_s})"
                    if rs_ratio is not None
                    else f"2단계: {name} ({ticker}) 점수 {score} (진입 {entry_date_str}, Vol/지수 {vb_s})"
                )
        except Exception:
            if os.path.exists(trend_path):
                try:
                    os.remove(trend_path)
                except OSError:
                    pass
        finally:
            if not scan_verbose:
                sys.stdout.write(
                    f"\r  후보 스캔 {100.0 * idx / total:5.1f}% ({idx}/{total})    "
                )
                sys.stdout.flush()
            else:
                if idx == 1 or idx % 100 == 0:
                    print(f"  후보 스캔 {100.0 * idx / total:5.1f}% ({idx}/{total})")

    if not scan_verbose:
        sys.stdout.write("\n")
        sys.stdout.flush()

    apply_fundamental_score_layer(new_matches)

    sorted_tickers = sorted(new_matches.keys(), key=lambda t: new_matches[t]["score"], reverse=True)
    for rank, t in enumerate(sorted_tickers, start=1):
        new_matches[t]["rank"] = rank

    want_charts: set[str]
    if chart_limit == 0:
        want_charts = set(sorted_tickers)
    else:
        want_charts = set(sorted_tickers[:chart_limit])

    print(
        f"  후보 스캔 끝: 현재 2단계 {len(sorted_tickers)}개. "
        f"추세 PNG 저장 중… ({len(want_charts)}종, 잠시 무출력일 수 있음)"
    )

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

    for t in want_charts:
        name = CANDIDATES[t][0]
        df = plot_cache.get(t)
        if df is None:
            continue
        path = os.path.join(charts_dir, f"{t}_trend.png")
        try:
            d = new_matches[t]
            rs_ratio = d.get("rs_ratio")
            vol_20 = d.get("vol_20_vs_prev20")
            three_month_return = (df["Close"].iloc[-1] / df["Close"].iloc[-60]) - 1
            rs_t = f"{rs_ratio:.2f}" if rs_ratio is not None else "-"
            v20_t = f"{vol_20:.2f}" if vol_20 is not None else "-"
            fig, ax = plt.subplots(figsize=(12, 6))
            ax.plot(df.index, df["Close"], label="종가", linewidth=1.5)
            ax.plot(df.index, df["MA50"], label="MA50", alpha=0.8)
            ax.plot(df.index, df["MA150"], label="MA150", alpha=0.8)
            ax.plot(df.index, df["MA200"], label="MA200", alpha=0.8)
            ax.set_title(
                f"{name} ({t}) #{d['rank']} 점수{d['score']} | 3M {three_month_return:.1%} | RS {rs_t} | Vol20 {v20_t}"
            )
            ax.set_xlabel("날짜")
            ax.set_ylabel("가격")
            ax.legend(loc="upper left")
            ax.grid(alpha=0.3)
            fig.tight_layout()
            fig.savefig(path, dpi=140)
            plt.close(fig)
        except Exception:
            new_matches[t]["chart"] = None
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    for fn in os.listdir(charts_dir):
        if not fn.endswith("_trend.png"):
            continue
        base = fn[: -len("_trend.png")]
        if base not in new_matches:
            try:
                os.remove(os.path.join(charts_dir, fn))
            except OSError:
                pass

    last_diff_added, last_diff_removed = _build_diff_lists(prev_signals, new_matches)
    last_analysis_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(signal_history_path, "w", encoding="utf-8") as f:
        json.dump(
            {"tickers": new_matches, "saved_at": last_analysis_time},
            f,
            ensure_ascii=False,
            indent=2,
        )

    today_iso = _calendar_today_iso("Asia/Seoul")
    rank_by_date_path = os.path.join(state_dir, "rank_by_date.json")
    rank_hist = _load_rank_by_date(rank_by_date_path)
    rank_hist_before_today = {k: v for k, v in rank_hist.items() if k != today_iso}

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
    rank_delta_meta = attach_rank_deltas_to_rows(top_table, rank_hist_before_today, today_iso)

    rank_hist[today_iso] = {str(t): int(new_matches[t]["rank"]) for t in new_matches}
    _prune_rank_by_date(rank_hist, today_iso)
    _save_rank_by_date(rank_by_date_path, rank_hist)

    sector_blocks = sector_blocks_charts_only(matches)

    payload = {
        "scanner_type": "tema_stage2",
        "last_analysis_time": last_analysis_time,
        "candidate_count": len(CANDIDATES),
        "matches": matches,
        "sector_blocks": sector_blocks,
        "sector_summary": sector_summary,
        "sector_score_table": sector_score_table,
        "top_table": top_table,
        "last_diff_added": last_diff_added,
        "last_diff_removed": last_diff_removed,
        "diff_snapshot_date": today_iso,
        "rank_delta_meta": rank_delta_meta,
        "scoring": {
            "scanner_type": "tema_stage2",
            "description": "총점=최근진입+RS(가격+시총·영업 품질, RS상한 내)+거래량+Vol/지수. 재무 가점은 RS 버킷에 합쳐 잡주(초소형·열위 재무) 억제. SCORE_FUND_DISABLE=1 로 재무만 끔.",
            "max_trend_charts": chart_limit,
            "summary_table_rows": summary_table_rows,
            "rank_delta_note": "Δ순위: 스냅샷일(KST) 기준 달력 1·3·6일 전 날짜에 저장된 순위(해당 일 없으면 그 이전 최근일) 대비. +는 순위 상승(숫자 감소). 티커 대소문자 통일해 조회.",
        },
    }

    results_path = os.path.join(base_dir, "results_web.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    DISPLAY.update(
        {
            "signal_times": {t: d["entry"] for t, d in new_matches.items()},
            "last_analysis_time": last_analysis_time,
            "last_diff_added": last_diff_added,
            "last_diff_removed": last_diff_removed,
            "matches": matches,
            "sector_blocks": sector_blocks,
            "sector_summary": sector_summary,
            "sector_score_table": sector_score_table,
            "top_table": top_table,
            "candidate_count": len(CANDIDATES),
            "scoring": payload["scoring"],
            "rank_delta_meta": rank_delta_meta,
        }
    )

    print(f"[{last_analysis_time}] 분석 완료: {len(new_matches)}개 → {results_path}")
    print(f"  신규: {len(last_diff_added)} / 탈락: {len(last_diff_removed)}")
    return payload


def load_display_from_export(base_dir: str) -> bool:
    """results_web.json만 읽어 DISPLAY 채움 (NAS 또는 로컬 미리보기)."""
    path = os.path.join(base_dir, "results_web.json")
    if not os.path.isfile(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    matches = list(data.get("matches", []))
    matches.sort(key=lambda x: (-float(x.get("score") or 0), x.get("ticker", "")))
    sector_score_table = data.get("sector_score_table") or sector_score_table_from_matches(matches)
    sector_summary = [(r["sector"], r["count"]) for r in sector_score_table]
    top_table = data.get("top_table")
    if not top_table:
        n = int((data.get("scoring") or {}).get("summary_table_rows") or 30)
        top_table = matches[: max(1, n)]
    for i, m in enumerate(matches, 1):
        m["rank"] = int(i)
    tr = {m.get("ticker"): m.get("rank") for m in matches if m.get("ticker")}
    for r in top_table:
        tid = r.get("ticker")
        if tid and tid in tr:
            r["rank"] = tr[tid]
    sector_blocks = sector_blocks_charts_only(matches)
    DISPLAY.update(
        {
            "signal_times": {m["ticker"]: m["entry"] for m in matches},
            "last_analysis_time": data.get("last_analysis_time"),
            "last_diff_added": data.get("last_diff_added", []),
            "last_diff_removed": data.get("last_diff_removed", []),
            "matches": matches,
            "sector_blocks": sector_blocks,
            "sector_summary": sector_summary,
            "sector_score_table": sector_score_table,
            "top_table": top_table,
            "candidate_count": data.get("candidate_count", 0),
            "scoring": data.get("scoring"),
            "rank_delta_meta": data.get("rank_delta_meta") or {},
        }
    )
    return True


def main(argv: list[str] | None = None) -> int:
    _configure_stdio_utf8()
    args = list(argv) if argv is not None else sys.argv[1:]
    if args:
        out_dir = os.path.abspath(args[0])
    else:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tema_stage2_data")
    run_analysis_export(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
