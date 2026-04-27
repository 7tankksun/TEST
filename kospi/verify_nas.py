"""NAS/로컬에서 results_web.json·charts 경로를 점검 (실행: python verify_nas.py)"""
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
P_ENV = os.environ.get("PAYLOAD_DIR", "")

paths = []
if P_ENV:
    paths.append((os.path.join(P_ENV, "results_web.json"), f"PAYLOAD_DIR + results_web.json (PAYLOAD_DIR={P_ENV!r})"))
    paths.append(
        (os.path.join(P_ENV, "nas_web_payload", "results_web.json"), "PAYLOAD_DIR + nas_web_payload/...")
    )
paths.append((os.path.join(HERE, "results_web.json"), "kospi 루트 (HERE)"))
paths.append((os.path.join(HERE, "nas_web_payload", "results_web.json"), "kospi/nas_web_payload (run_local_export 기본)"))


def main():
    print("kospi 경로 점검\n" + "-" * 50)
    found = None
    for p, label in paths:
        ok = os.path.isfile(p)
        size = os.path.getsize(p) if ok else 0
        st = "OK" if ok else "없음"
        print(f"  [{st}] {label}\n        {p}")
        if ok and size > 0:
            found = p
    print("-" * 50)
    if not found:
        print("없음: run_local_export.py 를 PC에서 한 번 실행하세요 (nas_web_payload 생성).")
        return 1
    try:
        with open(found, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print("JSON 읽기 실패:", e)
        return 1
    m = d.get("matches") or []
    ch = os.path.join(os.path.dirname(found), "charts")
    n_png = 0
    if os.path.isdir(ch):
        n_png = len([x for x in os.listdir(ch) if x.endswith("_trend.png")])
    print(f"  사용 파일: {found}")
    print(f"  last_analysis: {d.get('last_analysis_time')}")
    print(f"  matches: {len(m)} / charts: {n_png} PNG in {ch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
