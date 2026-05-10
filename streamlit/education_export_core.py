# -*- coding: utf-8 -*-
"""학군·교육 지역 대시보드용 results_web.json 생성 (포털 내 edu_data)."""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGIONS_FILE = HERE / "edu_data" / "regions.json"


def run_education_export(base_dir: str) -> dict:
    """edu_data/regions.json을 읽어 base_dir/results_web.json에 기록."""
    regions: list = []
    if REGIONS_FILE.is_file():
        with open(REGIONS_FILE, "r", encoding="utf-8") as f:
            regions = json.load(f)
    os.makedirs(base_dir, exist_ok=True)
    last_export_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "last_export_time": last_export_time,
        "regions": regions,
        "source_regions_file": str(REGIONS_FILE),
    }
    out_path = os.path.join(base_dir, "results_web.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload
