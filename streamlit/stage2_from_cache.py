from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from mansfield_rs import resolve_rs_for_score

KST = "Asia/Seoul"


def _normalize_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        except Exception:
            pass
    return df


def _load_tema_bench_closes() -> pd.Series | None:
    """테마 RS용 벤치 종가 시계열(일봉). 기본 ^KS11, `TEMA_BENCH_SYMBOL`로 변경 가능."""

    sym = (os.environ.get("TEMA_BENCH_SYMBOL") or "^KS11").strip() or "^KS11"
    try:
        raw = yf.download(sym, period="3y", interval="1d", progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            return None
        raw = _normalize_df_columns(raw)
        if "Close" not in raw.columns:
            return None
        s = raw["Close"].astype(float)
        ix = pd.DatetimeIndex(pd.to_datetime(s.index, errors="coerce"))
        if ix.tz is not None:
            ix = ix.tz_convert("Asia/Seoul").tz_localize(None)
        s.index = ix.normalize()
        return s[~s.index.duplicated(keep="last")].sort_index()
    except Exception:
        return None


def _safe_rs_extra_float(x) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
        if isinstance(v, float) and (pd.isna(v) or abs(v) == float("inf")):
            return None
        return v
    except (TypeError, ValueError):
        return None


@dataclass
class ScoreRow:
    ticker: str
    name: str
    market: str
    sector: str
    score: float
    close: float
    ret_20d: float
    ret_60d: float
    rs_ratio: float
    volume_ratio: float
    stage2_cond: bool
    date: str
    rs_model: str | None = None
    mansfield_weekly_rs: float | None = None
    mansfield_rs_mean_52w: float | None = None
    mansfield_weeks: float | None = None


def _now_kst() -> str:
    return datetime.now(tz=pd.Timestamp.now(tz=KST).tz).strftime("%Y-%m-%d %H:%M:%S")


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"items": {}, "active_set": [], "rank_prev": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"items": {}, "active_set": [], "rank_prev": {}}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_rank_by_date_disk(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_rank_by_date_disk(path: Path, hist: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


def _prune_rank_hist(hist: dict, today_iso: str, keep_days: int = 400) -> None:
    """kospi_export_core._prune_rank_by_date 와 동일."""
    try:
        t_anchor = date.fromisoformat(today_iso)
    except ValueError:
        return
    cutoff = (t_anchor - timedelta(days=keep_days)).isoformat()
    for k in list(hist.keys()):
        if isinstance(k, str) and len(k) == 10 and k < cutoff:
            del hist[k]


def _load_universe_meta(cache_dir: Path) -> dict[str, dict]:
    p = cache_dir / "universe_meta.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    return d.get("items") or {}


def _sector_map_from_candidates() -> dict[str, str]:
    try:
        from candidates_data import CANDIDATES
    except Exception:
        return {}
    m: dict[str, str] = {}
    for t, info in CANDIDATES.items():
        if not isinstance(info, (list, tuple)) or len(info) < 2:
            continue
        sec = str(info[1] or "")
        if " - " in sec:
            sec = sec.split(" - ", 1)[1]
        m[t] = sec.strip() or "미분류"
    return m


def _resolve_sector_row(ticker: str, sector_map: dict[str, str], meta: dict) -> str:
    base = sector_map.get(ticker, "미분류")
    extra = ""
    try:
        from candidates_data import CANDIDATES

        ci = CANDIDATES.get(ticker)
        if isinstance(ci, (list, tuple)) and len(ci) > 1:
            extra = str(ci[1] or "")
    except Exception:
        pass
    from surge_sector_resolve import resolve_surge_sector

    return resolve_surge_sector(
        ticker=ticker,
        name=str(meta.get("name") or ""),
        payload_sector=base,
        extra_hint=extra,
    )


def _yf_cache_repair() -> None:
    _syn = str(Path(__file__).resolve().parent.parent)
    if _syn not in sys.path:
        sys.path.insert(0, _syn)
    try:
        from yfinance_cache_repair import try_repair_with_message

        try_repair_with_message()
    except ImportError:
        pass


def _fetch_ticker_fundamentals(ticker: str) -> tuple[float | None, float | None]:
    """코스피 export와 동일: 시가총액(원), TTM 영업이익률(0~1)."""
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


def _calendar_today_kst() -> date:
    return pd.Timestamp.now(tz=KST).date()


def _max_cache_bar_date(raw: pd.DataFrame) -> date | None:
    if raw is None or raw.empty or "datetime" not in raw.columns:
        return None
    dts = pd.to_datetime(raw["datetime"], errors="coerce", utc=True)
    dts = dts.dropna()
    if dts.empty:
        return None
    return pd.Timestamp(dts.max()).tz_convert(KST).date()


def _max_kst_bar_date_strictly_before(raw: pd.DataFrame, t0: date) -> date | None:
    """캐시 전체 일봉 중 KST 날짜가 t0 미만인 것의 최댓값(직전 거래일·이전 봉 앵커)."""

    if raw is None or raw.empty or "datetime" not in raw.columns:
        return None
    dts = pd.to_datetime(raw["datetime"], errors="coerce", utc=True)
    dts = dts.dropna()
    if dts.empty:
        return None
    ds = dts.dt.tz_convert(KST).dt.normalize().dt.date
    sub = ds[ds < t0]
    if sub.empty:
        return None
    mx = sub.max()
    return mx if isinstance(mx, date) else pd.Timestamp(mx).date()


def _score_snapshot_at_pos(
    ticker: str,
    close: pd.Series,
    volume: pd.Series,
    dts: pd.Series,
    pos: int,
    meta: dict,
    sector_map: dict[str, str],
    *,
    min_bars: int,
    bench_master: pd.Series | None = None,
) -> ScoreRow | None:
    ma200_need = 199
    base_need = max(ma200_need, 60)
    min_b_full = max(int(min_bars), base_need + 1)
    need_pos = min_b_full - 1
    row_count = len(close)
    if pos < 0 or row_count < min_b_full or pos < need_pos:
        return None

    ma50 = close.rolling(50).mean().iloc[pos]
    ma200 = close.rolling(200).mean().iloc[pos]
    if pd.isna(ma50) or pd.isna(ma200):
        return None

    cur = float(close.iloc[pos])
    ret_20d = (cur / float(close.iloc[pos - 20]) - 1.0) * 100 if pos >= 20 else 0.0
    ret_60d = (cur / float(close.iloc[pos - 60]) - 1.0) * 100

    idx_kst = (
        pd.to_datetime(dts, utc=True, errors="coerce")
        .dt.tz_convert(KST)
        .dt.normalize()
        .dt.tz_localize(None)
    )
    stock_ix = pd.Series(close.astype(float).values, index=idx_kst)
    bench_ix: pd.Series | None = None
    if bench_master is not None and not bench_master.empty:
        bench_ix = bench_master.reindex(idx_kst, method="ffill")

    rs_ratio_val: float | None = None
    rs_model: str | None = None
    mf_wk = mf_m = mf_weeks = None
    if bench_ix is not None and bool(bench_ix.notna().any()):
        rs_ratio_val, _, _, rs_ex = resolve_rs_for_score(stock_ix, bench_ix, market="tema")
        rs_model = str(rs_ex["rs_model"]) if rs_ex.get("rs_model") is not None else None
        if rs_model == "mansfield_weekly_52w":
            mf_wk = _safe_rs_extra_float(rs_ex.get("mansfield_weekly_rs"))
            mf_m = _safe_rs_extra_float(rs_ex.get("mansfield_rs_mean_52w"))
            mf_weeks = _safe_rs_extra_float(rs_ex.get("mansfield_weeks"))
    if rs_ratio_val is None and pos >= 60:
        rs_ratio_val = cur / float(close.iloc[pos - 60])
        if rs_model is None:
            rs_model = "tema_fallback_60d_price"
    rs_ratio = round(float(rs_ratio_val), 4) if rs_ratio_val is not None else 0.0
    if rs_ratio_val is None and rs_model is None:
        rs_model = "tema_rs_unavailable"

    v20 = volume.iloc[pos - 19 : pos + 1].mean() if pos >= 19 else volume.iloc[: pos + 1].mean()
    v5 = volume.iloc[pos - 4 : pos + 1].mean() if pos >= 4 else volume.iloc[: pos + 1].mean()
    volume_ratio = float(v5 / v20) if v20 > 0 else 0.0

    cond = bool(cur > float(ma50) > float(ma200) and ret_60d > 0)
    score = max(min(ret_20d, 40), -20) + max(min(ret_60d, 60), -20) + (volume_ratio - 1.0) * 25
    score = round(score, 2)

    dt_val = dts.iloc[pos]
    if pd.isna(dt_val):
        return None

    return ScoreRow(
        ticker=ticker,
        name=meta.get("name") or ticker,
        market=meta.get("market") or ("코스닥" if ticker.endswith(".KQ") else "코스피"),
        sector=_resolve_sector_row(ticker, sector_map, meta),
        score=score,
        close=round(cur, 3),
        ret_20d=round(ret_20d, 2),
        ret_60d=round(ret_60d, 2),
        rs_ratio=rs_ratio,
        volume_ratio=round(volume_ratio, 3),
        stage2_cond=cond,
        date=pd.Timestamp(dt_val).tz_convert(KST).strftime("%Y-%m-%d"),
        rs_model=rs_model,
        mansfield_weekly_rs=mf_wk,
        mansfield_rs_mean_52w=mf_m,
        mansfield_weeks=mf_weeks,
    )


def _calc_one_calendar_asof(
    ticker: str,
    one: pd.DataFrame,
    meta: dict,
    sector_map: dict[str, str],
    *,
    min_bars: int,
    asof: date,
    bench_master: pd.Series | None = None,
) -> ScoreRow | None:
    """캘린더 asof일(KST) 마감까지의 일봉만 사용해 해당일 스냅샷 점수(코스피식 as-of와 동일한 날짜 기준)."""

    if one.empty:
        return None
    one = one.copy()
    one["datetime"] = pd.to_datetime(one["datetime"], errors="coerce", utc=True)
    one = one.dropna(subset=["datetime"])
    one["_d"] = one["datetime"].dt.tz_convert(KST).dt.normalize().dt.date
    one = one.loc[one["_d"] <= asof].sort_values("datetime")
    if one.empty:
        return None

    close = one["Close"].astype(float).reset_index(drop=True)
    volume = one["Volume"].astype(float).fillna(0.0).reset_index(drop=True)
    dts = one["datetime"].reset_index(drop=True)
    pos = len(close) - 1
    return _score_snapshot_at_pos(
        ticker,
        close,
        volume,
        dts,
        pos,
        meta,
        sector_map,
        min_bars=min_bars,
        bench_master=bench_master,
    )


def _df_stage2_zone_for_chart(one: pd.DataFrame, asof: date, *, min_bars: int) -> tuple[pd.DataFrame, pd.Series] | None:
    """캐시 일봉 → 코스피 차트와 동일 스타일용 OHLCV+MA+stage2 구간(스코어링과 동일 조건: MA50>MA200, 60일수익>0)."""

    if one.empty:
        return None
    sub = one.copy()
    sub["datetime"] = pd.to_datetime(sub["datetime"], errors="coerce", utc=True)
    sub = sub.dropna(subset=["datetime"])
    sub["_d"] = sub["datetime"].dt.tz_convert(KST).dt.normalize().dt.date
    sub = sub.loc[sub["_d"] <= asof].sort_values("datetime")
    if len(sub) < max(200, int(min_bars)):
        return None
    idx = pd.DatetimeIndex(
        pd.to_datetime(sub["datetime"], utc=True).dt.tz_convert(KST).dt.tz_localize(None).values
    )
    df = pd.DataFrame(
        {
            "Close": pd.to_numeric(sub["Close"], errors="coerce").astype(float).values,
        },
        index=idx,
    )
    df = df[~df.index.duplicated(keep="last")]
    if len(df) < max(200, int(min_bars)):
        return None
    df["MA50"] = df["Close"].rolling(50).mean()
    df["MA200"] = df["Close"].rolling(200).mean()
    ret60 = (df["Close"] / df["Close"].shift(60) - 1.0) * 100.0
    zone = ((df["Close"] > df["MA50"]) & (df["MA50"] > df["MA200"]) & (ret60 > 0)).fillna(False)
    return df, zone


def _write_stage2_trend_png(
    df: pd.DataFrame,
    stage2_zone: pd.Series,
    ticker: str,
    path: Path,
) -> bool:
    """코스피 export `_write_chart` 와 동일 레이아웃(Agg 백엔드)."""

    try:
        import warnings

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        warnings.filterwarnings("ignore", message=".*Glyph.*", category=UserWarning)
    except Exception:
        return False
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
        plt.plot(df.index[-250:], df["Close"].iloc[-250:], color="#1A1A1A", lw=1.2, label="Price")
        plt.plot(df.index[-250:], df["MA50"].iloc[-250:], color="#2196F3", lw=1.5, ls="--", label="50MA")
        plt.plot(df.index[-250:], df["MA200"].iloc[-250:], color="#F44336", lw=2, label="200MA")
        plt.title(f"STAGE 2 ACTIVE: {ticker}", fontsize=12, fontweight="bold")
        plt.xlim(df.index[-250], df.index[-1])
        tail = df["Close"].iloc[-250:]
        plt.ylim(float(tail.min()) * 0.95, float(tail.max()) * 1.05)
        plt.legend(loc="upper left", fontsize="small", frameon=True)
        plt.grid(True, linestyle=":", alpha=0.4)
        plt.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(str(path), dpi=120)
        plt.close(fig)
        return True
    except Exception:
        try:
            import matplotlib.pyplot as plt

            plt.close("all")
        except Exception:
            pass
        return False


def _sync_charts_tema_cache(
    *,
    matches: list[dict],
    raw_by_ticker: dict[str, pd.DataFrame],
    charts_dir: Path,
    t0: date,
    min_bars: int,
) -> None:
    """상위 테이블 종목에 대해 `{{ticker}}_trend.png` 생성·정리 (앱 차트 뷰어용)."""

    want = {str(m.get("ticker") or "") for m in matches if m.get("ticker")}
    for m in matches:
        t = str(m.get("ticker") or "")
        if not t:
            m["chart"] = None
            continue
        one = raw_by_ticker.get(t)
        pair = _df_stage2_zone_for_chart(one, t0, min_bars=min_bars) if one is not None else None
        if pair is None:
            m["chart"] = None
            continue
        df, zone = pair
        fn = f"{t}_trend.png"
        out_p = charts_dir / fn
        if _write_stage2_trend_png(df, zone, t, out_p):
            m["chart"] = fn
        else:
            m["chart"] = None
    if charts_dir.is_dir():
        for p in charts_dir.glob("*_trend.png"):
            if not p.is_file():
                continue
            base = p.name[: -len("_trend.png")]
            if base not in want:
                try:
                    p.unlink()
                except OSError:
                    pass


def run_stage2(
    cache_dir: Path,
    out_dir: Path,
    hold_confirm: int = 2,
    top_n: int = 30,
    min_bars: int = 220,
) -> dict:
    cache_daily = cache_dir / "ohlcv_daily.parquet"
    if not cache_daily.exists():
        raise FileNotFoundError(f"캐시 파일 없음: {cache_daily}")

    raw = pd.read_parquet(cache_daily)
    if raw.empty:
        raise ValueError("캐시 데이터가 비어 있습니다.")

    _yf_cache_repair()

    bench_master = _load_tema_bench_closes()

    universe_meta = _load_universe_meta(cache_dir)
    sector_map = _sector_map_from_candidates()
    tickers = sorted(set(raw["ticker"].astype(str)))
    raw_by_ticker: dict[str, pd.DataFrame] = {}
    for t, g in raw.groupby(raw["ticker"].astype(str), sort=False):
        raw_by_ticker[str(t)] = g[["ticker", "datetime", "Close", "Volume"]].copy()

    t_cal = _calendar_today_kst()
    last_bar = _max_cache_bar_date(raw)
    t0 = min(t_cal, last_bar) if last_bar is not None else t_cal

    cal1 = t0 - timedelta(days=1)
    prev_bar = _max_kst_bar_date_strictly_before(raw, t0)
    # Δ1d: 앱·rank_delta_utils 는 달력 t0-1 키를 조회하지만, 잘라 쓸 날짜는 직전 봉이 안정적(주말·휴장·경계).
    asof_for_1d = prev_bar if prev_bar is not None else cal1

    compute_asof: list[tuple[int, date]] = [
        (0, t0),
        (1, asof_for_1d),
        (3, t0 - timedelta(days=3)),
        (6, t0 - timedelta(days=6)),
    ]
    # rank_by_date.json 키는 코스피·attach_rank_deltas 와 동일하게 달력 t0·t0-1·t0-3·t0-6
    disk_key_for_off: dict[int, date] = {
        0: t0,
        1: cal1,
        3: t0 - timedelta(days=3),
        6: t0 - timedelta(days=6),
    }

    rank_maps: dict[int, dict[str, int]] = {}
    rows_t0: list[ScoreRow] = []

    for off, asof_d in compute_asof:
        batch_rows: list[ScoreRow] = []
        for t in tickers:
            one = raw_by_ticker.get(t)
            if one is None:
                continue
            r = _calc_one_calendar_asof(
                ticker=t,
                one=one,
                meta=universe_meta.get(t, {}),
                sector_map=sector_map,
                min_bars=min_bars,
                asof=asof_d,
                bench_master=bench_master,
            )
            if r is not None:
                batch_rows.append(r)
        ranked_batch = sorted(batch_rows, key=lambda x: x.score, reverse=True)
        rank_maps[off] = {x.ticker: i + 1 for i, x in enumerate(ranked_batch)}
        if off == 0:
            rows_t0 = batch_rows

    ranked = sorted(rows_t0, key=lambda x: x.score, reverse=True)
    rank_now = rank_maps.get(0) or {}

    # Streamlit이 _apply_rank_delta_enrichment으로 state/rank_by_date.json을 읽어 Δ를 다시 붙임.
    # 키는 달력 t0·t0-1·t0-3·t0-6 이고, off=1 값은 직전 봉 날짜로 잘라 계산한 순위를 t0-1 키에 저장.
    rank_by_date_path = out_dir / "state" / "rank_by_date.json"
    rank_hist_disk = _load_rank_by_date_disk(rank_by_date_path)
    today_iso = t0.isoformat()
    for off, _slice_date in compute_asof:
        disk_d = disk_key_for_off[off]
        mp = rank_maps.get(off) or {}
        rank_hist_disk[disk_d.isoformat()] = {str(k): int(v) for k, v in mp.items()}
    _prune_rank_hist(rank_hist_disk, today_iso)
    _save_rank_by_date_disk(rank_by_date_path, rank_hist_disk)

    state_path = out_dir / "state" / "stage2_state.json"
    state = _load_state(state_path)
    items = state.get("items") or {}
    active_prev = set(state.get("active_set") or [])
    active_now: set[str] = set()
    for r in ranked:
        rec = items.get(r.ticker, {"in_streak": 0, "out_streak": 0, "active": False})
        if r.stage2_cond:
            rec["in_streak"] = int(rec.get("in_streak", 0)) + 1
            rec["out_streak"] = 0
            if not rec.get("active", False) and rec["in_streak"] >= hold_confirm:
                rec["active"] = True
        else:
            rec["out_streak"] = int(rec.get("out_streak", 0)) + 1
            rec["in_streak"] = 0
            if rec.get("active", False) and rec["out_streak"] >= hold_confirm:
                rec["active"] = False
        rec["last_score"] = r.score
        items[r.ticker] = rec
        if rec.get("active", False):
            active_now.add(r.ticker)

    added = sorted(active_now - active_prev)
    removed = sorted(active_prev - active_now)

    top_active = [r for r in ranked if r.ticker in active_now][:top_n]
    rank_1d = rank_maps.get(1) or {}
    rank_3d = rank_maps.get(3) or {}
    rank_6d = rank_maps.get(6) or {}
    matches: list[dict] = []
    for r in top_active:
        cr = rank_now.get(r.ticker)
        d1 = rank_1d.get(r.ticker)
        delta_1d = "—" if cr is None or d1 is None else f"{int(d1) - int(cr):+d}"
        d3 = rank_3d.get(r.ticker)
        delta_3d = "—" if cr is None or d3 is None else f"{int(d3) - int(cr):+d}"
        d6 = rank_6d.get(r.ticker)
        delta_6d = "—" if cr is None or d6 is None else f"{int(d6) - int(cr):+d}"
        mcap, opm = _fetch_ticker_fundamentals(r.ticker)
        mrow: dict = {
            "ticker": r.ticker,
            "name": r.name,
            "market": r.market,
            "sector": r.sector,
            "score": r.score,
            "rank": int(cr) if cr is not None else None,
            "entry": r.date,
            "ret_3m_pct": r.ret_60d,
            "ret_since_entry_pct": r.ret_20d,
            "rs_ratio": r.rs_ratio,
            "rank_delta_1d": delta_1d,
            "rank_delta_3d": delta_3d,
            "rank_delta_6d": delta_6d,
            "chart": None,
            "market_cap": mcap,
            "operating_margin": opm,
        }
        if r.rs_model:
            mrow["rs_model"] = r.rs_model
        if r.mansfield_weekly_rs is not None:
            mrow["mansfield_weekly_rs"] = r.mansfield_weekly_rs
        if r.mansfield_rs_mean_52w is not None:
            mrow["mansfield_rs_mean_52w"] = r.mansfield_rs_mean_52w
        if r.mansfield_weeks is not None:
            mrow["mansfield_weeks"] = r.mansfield_weeks
        matches.append(mrow)

    charts_dir = out_dir / "charts"
    _sync_charts_tema_cache(
        matches=matches,
        raw_by_ticker=raw_by_ticker,
        charts_dir=charts_dir,
        t0=t0,
        min_bars=min_bars,
    )

    payload = {
        "scanner_type": "tema_stage2_cache",
        "last_analysis_time": _now_kst(),
        "diff_snapshot_date": t0.isoformat(),
        "diff_baseline_date": datetime.now().strftime("%Y-%m-%d"),
        "last_diff_added": added,
        "last_diff_removed": removed,
        "top_table": matches,
        "matches": matches,
        "signal_times": {},
        "scoring": {
            "source": "cache_only",
            "hold_confirm": hold_confirm,
            "top_n": top_n,
            "min_bars": min_bars,
            "min_rows_for_rank_delta_hint": int(min_bars) + 6,
            "universe_count": len(tickers),
            "ranked_count": len(ranked),
            "active_count": len(active_now),
            "rank_delta_note": "Δ순위: 앵커 t0=min(오늘 KST, 캐시 최종 봉). Δ1d는 직전 봉 날짜(KST)로 잘라 순위를 구하고 rank_by_date 키는 달력 t0-1에 저장. Δ3d·Δ6d는 달력 t0-3·t0-6. 시총·영업이익률은 상위 활성만 yfinance.",
            "rs_note": "RS: 기본 Mansfield(주간 RS÷직전52주 평균, TEMA_RS_MODE·TEMA_MANSFIELD_WEEKS). legacy=63일 종·벤치. 벤치는 TEMA_BENCH_SYMBOL(기본^KS11). 벤치·RS 불가 시 60일 전 종가 대비 비율·rs_model 참고.",
        },
        "index": {
            "tone": "unknown",
            "headline": "캐시 기반 스코어링(지수판정 생략)",
            "as_of": t0.isoformat(),
        },
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results_web.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    state["items"] = items
    state["active_set"] = sorted(active_now)
    state["rank_prev"] = {r.ticker: rank_now[r.ticker] for r in ranked}
    _save_state(state_path, state)
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="캐시 기반 Stage2 스코어러")
    ap.add_argument("--cache-dir", default=str(Path(__file__).resolve().parent / "tema_cache_data" / "cache"))
    ap.add_argument("--out-dir", default=str(Path(__file__).resolve().parent / "tema_stage2_data"))
    ap.add_argument("--hold-confirm", type=int, default=2, help="신규/탈락 확정 연속 횟수")
    ap.add_argument(
        "--top-n",
        type=int,
        default=30,
        help="요약/표시 상위 N (코스피 TOP_SUMMARY_ROWS 기본 30과 동일)",
    )
    ap.add_argument("--min-bars", type=int, default=220)
    args = ap.parse_args()

    payload = run_stage2(
        cache_dir=Path(args.cache_dir),
        out_dir=Path(args.out_dir),
        hold_confirm=args.hold_confirm,
        top_n=args.top_n,
        min_bars=args.min_bars,
    )
    print(
        json.dumps(
            {
                "last_analysis_time": payload.get("last_analysis_time"),
                "active_count": len(payload.get("top_table") or []),
                "added": len(payload.get("last_diff_added") or []),
                "removed": len(payload.get("last_diff_removed") or []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
