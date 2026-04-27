"""
나만의 API 스냅샷: catalog.json에 있는 active 항목만 HTTP 요청 → data/last_ok/ 에 UTF-8 JSON 저장.
키가 필요한 항목(FRED 등)은 해당 env가 있을 때만 시도. 실패/스킵은 manifest.json에 남김.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "catalog.json"
OUT_LAST = HERE / "data" / "last_ok"
OUT_HIST = HERE / "data" / "history"
MANIFEST = HERE / "data" / "manifest.json"

TIMEOUT = 45
UA = "api_hoard/1.0 (personal snapshot) "


def _redact_url(url: str) -> str:
    """last_ok JSON에 API 키가 그대로 남지 않게 마스킹."""
    if not url:
        return url
    s = re.sub(r"([?&]api_key=)[^&]+", r"\1***", url, flags=re.I)
    s = re.sub(r"([?&]key=)[^&]+", r"\1***", s, flags=re.I)
    s = re.sub(r"(/Key/)([^/]+)(/)", r"\1***\3", s)
    return s


# url_template {placeholder} -> 환경 변수 이름
_PLACEHOLDER_ENV: dict[str, str] = {
    "fred_api_key": "FRED_API_KEY",
    "eia_api_key": "EIA_API_KEY",
    "bok_key": "ECOS_API_KEY",
    "census_key": "CENSUS_API_KEY",
}


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        return
    p = HERE / ".env"
    if p.is_file():
        load_dotenv(p)


def _safe_name(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", s)[:200]


def _fetch(
    method: str,
    url: str,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    """(status, body_bytes, response_headers)"""
    req = urllib.request.Request(
        url,
        method=method.upper(),
        headers={
            "User-Agent": UA,
            "Accept": "application/json, */*;q=0.8",
            **(extra_headers or {}),
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = resp.read()
        return resp.getcode(), body, {k: v for k, v in resp.headers.items()}


def _format_url_template(tpl: str) -> str | None:
    """{fred_api_key} → FRED_API_KEY 등. 키 없으면 빈 문자열(스킵)."""
    names = re.findall(r"\{([a-zA-Z0-9_]+)\}", tpl)
    if not names:
        return tpl
    out = tpl
    for name in names:
        ev = _PLACEHOLDER_ENV.get(name) or f"{name.upper()}"
        v = (os.environ.get(ev) or "").strip()
        if not v:
            return ""
        out = out.replace("{" + name + "}", v)
    return out


def _run_one(
    item: dict[str, Any],
) -> dict[str, Any]:
    eid = item["id"]
    if not item.get("active", True):
        return {
            "id": eid,
            "ok": None,
            "skipped": "inactive",
            "message": (item.get("notes") or "")[:500],
        }

    method = (item.get("method") or "GET").upper()
    if item.get("url"):
        url = str(item["url"])
    else:
        tpl = item.get("url_template")
        if not tpl:
            return {"id": eid, "ok": False, "error": "no url or url_template"}
        url = _format_url_template(str(tpl))
        if not url:
            envs: list[str] = []
            if (item.get("auth") or {}).get("env"):
                envs.append(str((item.get("auth") or {}).get("env")))
            for n in re.findall(r"\{([a-zA-Z0-9_]+)\}", str(tpl or "")):
                ev2 = _PLACEHOLDER_ENV.get(n) or f"{n.upper()}"
                if ev2 not in envs:
                    envs.append(ev2)
            return {
                "id": eid,
                "ok": None,
                "skipped": "no_api_key",
                "env": ", ".join(envs) or (item.get("auth") or {}).get("env"),
            }

    t0 = time.perf_counter()
    try:
        code, body, _hdrs = _fetch(method, url)
        ms = (time.perf_counter() - t0) * 1000.0
        if code != 200:
            return {"id": eid, "ok": False, "http": code, "ms": round(ms, 1)}
        if len(body) < 8:
            return {
                "id": eid,
                "ok": False,
                "error": "body_too_small",
                "ms": round(ms, 1),
            }
        # JSON 검증
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            return {"id": eid, "ok": False, "error": f"not_json: {e}", "ms": round(ms, 1)}

        now = datetime.now(timezone.utc)
        out = {
            "api_id": eid,
            "fetched_utc": now.isoformat().replace("+00:00", "Z"),
            "source_url": _redact_url(url),
            "http_status": code,
            "response_json": data,
        }
        # 저장
        OUT_LAST.mkdir(parents=True, exist_ok=True)
        last_path = OUT_LAST / f"{_safe_name(eid)}.json"
        last_path.write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if os.environ.get("API_HOARD_HISTORY", "").strip() in ("1", "true", "yes", "on"):
            OUT_HIST.mkdir(parents=True, exist_ok=True)
            ts = now.strftime("%Y%m%dT%H%M%SZ")
            hpath = OUT_HIST / f"{_safe_name(eid)}_{ts}.json"
            hpath.write_text(
                json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return {
            "id": eid,
            "ok": True,
            "ms": round(ms, 1),
            "bytes": len(body),
            "file": str(last_path.relative_to(HERE)).replace("\\", "/"),
        }
    except urllib.error.HTTPError as e:
        return {"id": eid, "ok": False, "http": e.code, "error": str(e)[:200]}
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return {"id": eid, "ok": False, "error": type(e).__name__, "detail": str(e)[:200]}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    _load_dotenv()
    if not CATALOG.is_file():
        print("catalog.json 없음", file=sys.stderr)
        return 1

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = list(catalog.get("apis") or [])
    only = (os.environ.get("API_HOARD_ONLY", "") or "").strip()
    if only:
        ids = {x.strip() for x in only.split(",") if x.strip()}
        items = [x for x in items if x.get("id") in ids]

    results: list[dict[str, Any]] = []
    for it in items:
        r = _run_one(it)
        results.append(r)
        st = "OK" if r.get("ok") is True else "SKIP" if r.get("ok") is None else "FAIL"
        print(f"[{st}] {r.get('id')}: {r}")

    (HERE / "data").mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(
            {
                "run_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nmanifest: {MANIFEST}")
    n_ok = sum(1 for r in results if r.get("ok") is True)
    n_fail = sum(1 for r in results if r.get("ok") is False)
    n_skip = sum(1 for r in results if r.get("ok") is None)
    print(f"요약: 성공 {n_ok}  실패 {n_fail}  스킵(키없음/비활성) {n_skip}")
    try:
        from render_catalog_table import main as _render_table

        _render_table()
    except Exception as exc:  # noqa: BLE001
        print("catalog_table.html 갱신 생략:", exc, file=sys.stderr)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
