"""
로컬 PC 스케줄용: 전체 분석 후 NAS로 옮길 폴더만 생성합니다.
작업 스케줄러에서 예: python run_local_export.py

환경 변수:
  EXPORT_DIR         출력 폴더 (기본: 스크립트와 같은 위치의 nas_web_payload)
  MAX_TREND_CHARTS   추세 PNG 상위 N종 (기본 50, 0이면 2단계 전 종목)
  TOP_SUMMARY_ROWS   상단 요약 표 행 수 (미설정 시 MAX_TREND_CHARTS와 동일, 0일 땐 50)
  가점 가중치는 analysis_core — SCORE_MAX_* / SCORE_FUND_* / 기본 시총·영업 배치(SCORE_FUND_DISABLE=1 로 끔)
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from analysis_core import run_analysis_export


def main():
    out = os.environ.get("EXPORT_DIR", os.path.join(HERE, "nas_web_payload"))
    os.makedirs(out, exist_ok=True)
    print(f"출력 폴더: {out}")
    payload = run_analysis_export(out)
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
