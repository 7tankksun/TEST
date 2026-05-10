# -*- coding: utf-8 -*-
"""
APT 실거래 배치만 실행 (Streamlit 폴더 기준).

  py -3 run_apt_export.py

출력: 이 폴더의 apt_data/ (EXPORT_DIR·APT_PAYLOAD_DIR 미지정 시)
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from apt_analysis_core import format_apt_leaders_text, run_apt_export


def _default_export_dir() -> str:
    return os.path.join(HERE, "apt_data")


def main() -> None:
    out = (
        (os.environ.get("EXPORT_DIR") or "").strip()
        or (os.environ.get("APT_PAYLOAD_DIR") or "").strip()
        or _default_export_dir()
    )
    os.makedirs(out, exist_ok=True)
    print(f"출력 폴더: {out}")
    payload = run_apt_export(out)
    print()
    leaders = format_apt_leaders_text(payload.get("apt_sections", []))
    try:
        print(leaders)
    except UnicodeEncodeError:
        # Windows cp949 콘솔에서 일부 유니코드(예: em dash) 출력 실패 방지
        print(leaders.encode("cp949", errors="replace").decode("cp949", errors="replace"))
    print("완료.")
    print("  - results_web.json")
    print("  - charts/")
    print()
    rj = os.path.join(out, "results_web.json")
    print("Streamlit: 아래만 맞으면 APT 탭에 표시됩니다.")
    print(f"  EXPORT_DIR / APT_PAYLOAD_DIR = {out}")
    print(f"  APT_RESULTS_JSON = {rj}")


if __name__ == "__main__":
    main()
