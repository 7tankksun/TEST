"""
로컬 PC 스케줄용: KOSPI Stage2 분석 후 NAS로 옮길 폴더만 생성합니다.
작업 스케줄러 예: python run_local_export.py

환경 변수:
  EXPORT_DIR         출력 폴더 (기본: 이 스크립트와 같은 위치의 nas_web_payload)
  MAX_TREND_CHARTS   추세 PNG 상위 N종 (기본 50, 0이면 2단계 전 종목)
  TOP_SUMMARY_ROWS   상단 요약 표 행 수 (미설정 시 MAX_TREND_CHARTS와 유사, 0일 땐 50)
  KOSPI_BONUS_MARKET_CAP   시가총액 상대가점(이번 2단계 집합 내, 기본 1=ON, 0=OFF)
  KOSPI_BONUS_OPERATING_MARGIN  TTM 영업이익률 상대가점(기본 1=ON, 0=OFF)
  KOSPI_BONUS_MCAP_PTS   시총 가점 상한 (기본 15)
  KOSPI_BONUS_OPM_PTS    영업이익률 가점 상한 (기본 15)
  YFIN_USE_DEFAULT_SESSION_CACHE=1  yfinance 프로필 캐시 고정(기본은 매 실행 임시 폴더)
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from kospi_export_core import run_kospi_export


def main():
    out = os.environ.get("EXPORT_DIR", os.path.join(HERE, "nas_web_payload"))
    os.makedirs(out, exist_ok=True)
    print(f"출력 폴더: {out}")
    payload = run_kospi_export(out)
    top = list(payload.get("top_table") or [])
    if top:
        print()
        print("순위(총점 내림차순) - 웹 '총점 상위' 표와 동일")
        print(f"  {'순위':>4}  {'종목명':<16}  {'티커':<10}  {'총점':>7}")
        for r in top:
            rk = r.get("rank")
            try:
                rk_s = f"{int(rk):>4}" if rk is not None else "   -"
            except (TypeError, ValueError):
                rk_s = "   -"
            name = (r.get("name") or "")[:16]
            tkr = (r.get("ticker") or "")[:10]
            sc = float(r.get("score") or 0.0)
            print(f"  {rk_s}  {name:<16}  {tkr:<10}  {sc:7.2f}")
    print()
    print("완료. 이 폴더 전체를 NAS 웹 경로와 동기화하세요 (예: Synology Drive, rsync).")
    print("  - results_web.json")
    print("  - charts/")
    print("  - state/")


if __name__ == "__main__":
    main()
