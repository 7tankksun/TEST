# -*- coding: utf-8 -*-
"""
생활 포털(Streamlit) 데이터 일괄 갱신 — 윈도 작업 스케줄러용 단일 진입점.

  py -3 run_portal_batch.py

기본 동작 (인자 없음)
  • 코스피 / 코스닥 / 테마 Stage2(캐시) 만 실행
  • APT·교육은 데이터·로직이 달라 기본에 포함하지 않음

옵션
  --with-apt      APT 실거래 배치까지 포함 (별도 apt_data·로직)
  --apt-only      코스피·코스닥·테마 없이 APT만 실행
  --with-edu      교육 regions JSON 내보내기 포함

종료 코드: 일부라도 실패 시 1
"""

from __future__ import annotations

import argparse
import importlib
import sys
import traceback
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent


def _ensure_path() -> None:
    s = str(HERE)
    if s not in sys.path:
        sys.path.insert(0, s)


def _run_job(name: str, fn: Callable[[], None]) -> tuple[str, bool, str]:
    print(f"\n{'='*60}\n>> {name}\n{'='*60}", flush=True)
    try:
        fn()
        print(f"[OK] {name} 완료", flush=True)
        return name, True, ""
    except Exception as e:
        print(f"[FAIL] {name} 실패: {e}", flush=True)
        traceback.print_exc()
        return name, False, str(e)


def main() -> int:
    _ensure_path()
    ap = argparse.ArgumentParser(description="포털 배치: KOSPI·KOSDAQ·테마(기본), APT는 별도 opt-in")
    ap.add_argument("--with-apt", action="store_true", help="APT 실거래(apt_data)까지 실행")
    ap.add_argument("--apt-only", action="store_true", help="APT만 실행")
    ap.add_argument("--with-edu", action="store_true", help="교육 regions JSON 포함")
    args = ap.parse_args()

    apt_dir = HERE / "apt_data"
    failures: list[str] = []

    if args.apt_only:
        payload = __import__("apt_analysis_core").run_apt_export(str(apt_dir))
        from apt_analysis_core import format_apt_leaders_text

        print(format_apt_leaders_text(payload.get("apt_sections", [])))
        print("\nAPT 전용 실행 완료. 출력:", apt_dir)
        return 0

    frequent: list[tuple[str, Callable[[], None]]] = [
        (
            "KOSPI",
            lambda: importlib.import_module("kospi_export_core").run_kospi_export(
                str(HERE / "kospi_data")
            ),
        ),
        (
            "KOSDAQ",
            lambda: importlib.import_module("kosdaq_export_core").run_kosdaq_export(
                str(HERE / "kosdaq_data")
            ),
        ),
        (
            "테마주·Stage2(통합)",
            lambda: importlib.import_module("stage2_from_cache").run_stage2(
                cache_dir=HERE / "tema_cache_data" / "cache",
                out_dir=HERE / "tema_stage2_data",
                top_n=30,
            ),
        ),
    ]
    if args.with_edu:
        frequent.append(
            (
                "교육지역 JSON",
                lambda: importlib.import_module("education_export_core").run_education_export(
                    str(HERE / "edu_data")
                ),
            )
        )

    for name, fn in frequent:
        n, ok, _ = _run_job(name, fn)
        if not ok:
            failures.append(n)

    if args.with_apt:
        n, ok, _ = _run_job(
            "APT 실거래",
            lambda: importlib.import_module("apt_analysis_core").run_apt_export(
                str(apt_dir)
            ),
        )
        if not ok:
            failures.append(n)

    print("\n" + "=" * 60)
    if failures:
        print("실패한 작업:", ", ".join(failures))
        print("=" * 60)
        return 1
    print("전체 성공")
    print("=" * 60)
    print(f"\nStreamlit: {HERE}")
    print("  스캐너: kospi_data · kosdaq_data · tema_stage2_data / APT는 --with-apt 또는 --apt-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
