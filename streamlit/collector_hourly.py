from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
import warnings

import pandas as pd
import yfinance as yf

KST = "Asia/Seoul"


@dataclass
class UniverseRow:
    ticker: str
    name: str
    market: str


def _now_kst() -> str:
    return datetime.now(tz=pd.Timestamp.now(tz=KST).tz).strftime("%Y-%m-%d %H:%M:%S")


def _load_universe_from_xlsx(xlsx_path: Path) -> list[UniverseRow]:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Workbook contains no default style",
            category=UserWarning,
        )
        df = pd.read_excel(xlsx_path)
    required = {"단축코드", "한글 종목약명", "시장구분", "주식종류"}
    if not required.issubset(set(df.columns)):
        raise ValueError(f"필수 컬럼 누락: {sorted(required - set(df.columns))}")

    u = df.copy()
    u = u[u["주식종류"].astype(str).str.strip().eq("보통주")].copy()
    u["시장구분"] = u["시장구분"].astype(str).str.upper().str.strip()
    u = u[u["시장구분"].str.startswith(("KOSPI", "KOSDAQ"))].copy()
    u["단축코드"] = u["단축코드"].astype(str).str.strip().str.zfill(6)

    rows: list[UniverseRow] = []
    seen: set[str] = set()
    for _, r in u.iterrows():
        code = str(r["단축코드"])
        market_raw = str(r["시장구분"])
        if market_raw.startswith("KOSPI"):
            ticker = f"{code}.KS"
            market = "코스피"
        else:
            ticker = f"{code}.KQ"
            market = "코스닥"
        if ticker in seen:
            continue
        seen.add(ticker)
        rows.append(UniverseRow(ticker=ticker, name=str(r["한글 종목약명"]).strip(), market=market))
    return rows


def _chunked(items: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


def _download_batch(tickers: list[str], period: str, interval: str) -> pd.DataFrame:
    df = yf.download(
        tickers=tickers,
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if df is None or df.empty:
        return pd.DataFrame(columns=["ticker", "datetime", "Open", "High", "Low", "Close", "Volume"])

    out_rows: list[pd.DataFrame] = []
    if isinstance(df.columns, pd.MultiIndex):
        lv0 = set(df.columns.get_level_values(0))
        for t in tickers:
            if t not in lv0:
                continue
            one = df[t].copy()
            if one.empty:
                continue
            one = one.reset_index()
            one["ticker"] = t
            out_rows.append(one)
    else:
        one = df.copy().reset_index()
        one["ticker"] = tickers[0]
        out_rows.append(one)

    if not out_rows:
        return pd.DataFrame(columns=["ticker", "datetime", "Open", "High", "Low", "Close", "Volume"])

    merged = pd.concat(out_rows, ignore_index=True)
    ts_col = "Datetime" if "Datetime" in merged.columns else "Date"
    merged = merged.rename(columns={ts_col: "datetime"})
    keep = ["ticker", "datetime", "Open", "High", "Low", "Close", "Volume"]
    for c in keep:
        if c not in merged.columns:
            merged[c] = pd.NA
    return merged[keep].copy()


def _append_parquet(path: Path, incoming: pd.DataFrame) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if incoming.empty:
        if path.exists():
            prev = pd.read_parquet(path, columns=["ticker"])
            return 0, len(prev)
        return 0, 0

    incoming = incoming.copy()
    incoming["datetime"] = pd.to_datetime(incoming["datetime"], errors="coerce", utc=True)
    incoming = incoming.dropna(subset=["datetime", "ticker"]).copy()
    incoming["ticker"] = incoming["ticker"].astype(str).str.upper().str.strip()
    incoming = incoming.drop_duplicates(subset=["ticker", "datetime"], keep="last")
    incoming = incoming.sort_values(["ticker", "datetime"])
    new_rows = len(incoming)

    if path.exists():
        prev = pd.read_parquet(path)
        merged = pd.concat([prev, incoming], ignore_index=True)
        merged = merged.drop_duplicates(subset=["ticker", "datetime"], keep="last")
        merged = merged.sort_values(["ticker", "datetime"])
    else:
        merged = incoming

    merged.to_parquet(path, index=False)
    return new_rows, len(merged)


def _latest_cached_dates(path: Path) -> dict[str, pd.Timestamp]:
    if not path.exists():
        return {}
    prev = pd.read_parquet(path, columns=["ticker", "datetime"])
    if prev.empty:
        return {}
    prev["datetime"] = pd.to_datetime(prev["datetime"], errors="coerce", utc=True)
    prev = prev.dropna(subset=["datetime", "ticker"])
    if prev.empty:
        return {}
    g = prev.groupby(prev["ticker"].astype(str).str.upper().str.strip())["datetime"].max()
    return g.to_dict()


def _target_trading_day_utc() -> pd.Timestamp | None:
    """시장 최신 거래일(UTC 자정 기준) 추정."""
    try:
        idx = yf.download("^KS11", period="1mo", interval="1d", progress=False, auto_adjust=True)
        if idx is None or idx.empty:
            return None
        dti = pd.to_datetime(idx.index, utc=True)
        return pd.Timestamp(dti.max()).normalize()
    except Exception:
        return None


def run_collection(
    *,
    universe_xlsx: Path,
    out_dir: Path,
    batch_size: int = 80,
    daily_period: str = "540d",
    max_tickers: int | None = None,
) -> dict:
    universe = _load_universe_from_xlsx(universe_xlsx)
    if max_tickers and max_tickers > 0:
        universe = universe[:max_tickers]
    tickers = [u.ticker for u in universe]
    meta = {u.ticker: {"name": u.name, "market": u.market} for u in universe}

    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    daily_path = cache_dir / "ohlcv_daily.parquet"
    cached_latest = _latest_cached_dates(daily_path)
    target_day = _target_trading_day_utc()

    if target_day is None:
        # 인덱스 조회(rate-limit) 실패 시에도 전체 재수집을 피하기 위해
        # 캐시 최신일이 최근(어제 이후)이면 스킵한다.
        cutoff = (pd.Timestamp.now(tz=KST) - pd.Timedelta(days=1)).tz_convert("UTC").normalize()
        tickers_to_fetch = []
        for t in tickers:
            last_dt = cached_latest.get(t)
            if last_dt is None:
                tickers_to_fetch.append(t)
                continue
            if pd.Timestamp(last_dt).normalize() < cutoff:
                tickers_to_fetch.append(t)
    else:
        tickers_to_fetch = []
        for t in tickers:
            last_dt = cached_latest.get(t)
            if last_dt is None:
                tickers_to_fetch.append(t)
                continue
            if pd.Timestamp(last_dt).normalize() < target_day:
                tickers_to_fetch.append(t)

    frames_daily: list[pd.DataFrame] = []
    total = len(tickers_to_fetch)
    for i, batch in enumerate(_chunked(tickers_to_fetch, batch_size), start=1):
        print(f"[{i}] 수집중 ... {min(i * batch_size, total)}/{total}", flush=True)
        d = _download_batch(batch, period=daily_period, interval="1d")
        if not d.empty:
            d["interval"] = "1d"
            frames_daily.append(d)

    daily_df = pd.concat(frames_daily, ignore_index=True) if frames_daily else pd.DataFrame()

    d_new, d_total = _append_parquet(daily_path, daily_df)

    meta_path = cache_dir / "universe_meta.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "updated_at": _now_kst(),
                "universe_count": len(meta),
                "items": meta,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    return {
        "updated_at": _now_kst(),
        "universe_count": len(meta),
        "fetch_target_count": len(tickers_to_fetch),
        "daily_new_rows": d_new,
        "daily_total_rows": d_total,
        "cache_dir": str(cache_dir),
    }


def _patch_results_web_universe_cache_updated(results_path: Path, ts: str) -> bool:
    """Streamlit이 `last_analysis_time`만 보면 새벽 전체 스캔 시각에 고정되는 문제 방지: 캐시 갱신 시각을 별도 기록."""
    if not results_path.is_file():
        return False
    try:
        with results_path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False
        data["universe_cache_updated_at"] = ts
        data["universe_cache_source"] = "collector_hourly"
        with results_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[WARN] universe_cache_updated_at 패치 실패 {results_path}: {e}", flush=True)
        return False


def main() -> int:
    # yfinance SQLite 캐시 손상 시 ^KS11 등에서 DatabaseError('database disk image is malformed')
    _syn = str(Path(__file__).resolve().parent.parent)
    if _syn not in sys.path:
        sys.path.insert(0, _syn)
    try:
        from yfinance_cache_repair import try_repair_with_message

        try_repair_with_message()
    except ImportError:
        pass

    ap = argparse.ArgumentParser(description="KRX 유니버스 일봉 캐시 수집기(Δ3·Δ6 순위까지 여유 버퍼)")
    ap.add_argument(
        "--universe-xlsx",
        default=str(Path(__file__).resolve().parent / "ML" / "data_0840_20260501.xlsx"),
    )
    ap.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parent / "tema_cache_data"),
    )
    ap.add_argument("--batch-size", type=int, default=80)
    ap.add_argument(
        "--daily-period",
        default="540d",
        help="yfinance 일봉 조회 구간 (기본 약 1.5년·거래일 ≈±320, min_bars+6 버퍼용)",
    )
    ap.add_argument("--max-tickers", type=int, default=0, help="테스트용 티커 제한(0=전체)")
    args = ap.parse_args()

    result = run_collection(
        universe_xlsx=Path(args.universe_xlsx),
        out_dir=Path(args.out_dir),
        batch_size=args.batch_size,
        daily_period=args.daily_period,
        max_tickers=(args.max_tickers or None),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    streamlit_root = Path(__file__).resolve().parent
    ts = str(result.get("updated_at") or _now_kst())
    for sub in ("kospi_data", "kosdaq_data"):
        p = streamlit_root / sub / "results_web.json"
        ok = _patch_results_web_universe_cache_updated(p, ts)
        print(f"[universe_cache_updated_at] {sub}/results_web.json: {'updated' if ok else 'skipped'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
