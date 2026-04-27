"""
로컬 PC: 미국주식 Stage2 → NAS로 옮길 폴더(nas_web_payload) 생성.
  python run_local_export.py

환경 변수: EXPORT_DIR, MAX_TREND_CHARTS, TOP_SUMMARY_ROWS
  USA_BONUS_MARKET_CAP, USA_BONUS_OPERATING_MARGIN, USA_BONUS_MCAP_PTS, USA_BONUS_OPM_PTS
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from usa_export_core import run_usa_export


def main():
    out = os.environ.get("EXPORT_DIR", os.path.join(HERE, "nas_web_payload"))
    os.makedirs(out, exist_ok=True)
    print(f"출력 폴더: {out}")
    payload = run_usa_export(out)
    top = list(payload.get("top_table") or [])
    if top:
        print()
        print("Rank (by score) - same as web top table")
        print(f"  {'#':>4}  {'Name':<18}  {'Ticker':<10}  {'Score':>7}")
        for r in top:
            rk = r.get("rank")
            try:
                rk_s = f"{int(rk):>4}" if rk is not None else "   -"
            except (TypeError, ValueError):
                rk_s = "   -"
            name = (r.get("name") or "")[:18]
            tkr = (r.get("ticker") or "")[:10]
            sc = float(r.get("score") or 0.0)
            print(f"  {rk_s}  {name:<18}  {tkr:<10}  {sc:7.2f}")
    print()
    print("Done. Sync this folder to NAS (Synology Drive, rsync, etc.)")
    print("  - results_web.json, charts/, state/")


if __name__ == "__main__":
    main()
