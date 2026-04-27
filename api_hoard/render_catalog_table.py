r"""
catalog.json + data/manifest.json -> data/catalog_table.html
(브라우저로 열어 보면 "내가 쓸 수 있는 API"를 표로 볼 수 있음. AI/사람이 catalog id를 공유할 때에도 쓰기 좋음)
"""

from __future__ import annotations

import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "catalog.json"
MANIFEST = HERE / "data" / "manifest.json"
OUT = HERE / "data" / "catalog_table.html"


def _load_manifest() -> dict:
    if not MANIFEST.is_file():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _result_by_id(manifest: dict) -> dict:
    by: dict = {}
    for r in manifest.get("results") or []:
        i = r.get("id")
        if i:
            by[i] = r
    return by


def _status_cell(r: dict) -> str:
    if r.get("ok") is True:
        ms = r.get("ms", "")
        return f'<span class="ok">성공</span> ({ms} ms)'
    if r.get("ok") is None:
        sk = (r.get("skipped") or "").lower()
        if sk == "inactive":
            return '<span class="skip">스킵</span> (비활성 catalog)'
        if "no_api_key" in sk or sk == "no_api_key":
            env = r.get("env") or "?"
            return f'<span class="skip">스킵</span> (키 없음: {html.escape(str(env))})'
        return f'<span class="skip">스킵</span> {html.escape(str(r))}'
    if r.get("ok") is False:
        d = {k: v for k, v in r.items() if k not in ("id", "ok")}
        return f'<span class="fail">실패</span> {html.escape(json.dumps(d, ensure_ascii=False)[:200])}'
    return "— (manifest 없음)"


def _url_cell(entry: dict) -> str:
    u = (entry.get("url") or entry.get("url_template") or "").strip()
    if not u:
        return "—"
    if len(u) > 72:
        show = u[:35] + "…" + u[-30:]
    else:
        show = u
    return f'<a href="{html.escape(u, quote=True)}" title="{html.escape(u)}">{html.escape(show)}</a>'


def _auth_cell(entry: dict) -> str:
    a = entry.get("auth")
    if not a:
        return '<span class="ok">불필요</span>'
    env = (a.get("env") or "").strip()
    if env:
        return f"필요: <code>{html.escape(env)}</code>"
    return "확인"


def _cache_link(entry: dict, by_id: dict) -> str:
    eid = entry.get("id")
    r = by_id.get(eid) if eid else None
    if r and r.get("ok") is True and r.get("file"):
        # catalog_table.html 과 같은 data/ 아래 last_ok/xxx.json
        name = Path(r["file"]).name
        href = f"last_ok/{name}"
        return f'<a href="{html.escape(href, quote=True)}">열기</a> <code>{html.escape(name)}</code>'
    return "— (verify 성공 후)"


def render() -> str:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    manifest = _load_manifest()
    by_id = _result_by_id(manifest)
    run_utc = (manifest.get("run_utc") or "").replace("T", " ").replace("Z", " UTC")

    rows: list[str] = []
    for e in catalog.get("apis") or []:
        eid = e.get("id", "")
        r = by_id.get(eid, {})
        rows.append(
            "<tr>"
            f'<td><code>{html.escape(str(eid))}</code></td>'
            f'<td>{html.escape(str(e.get("name") or ""))}</td>'
            f'<td>{html.escape(str(e.get("kind") or ""))}</td>'
            f'<td>{"O" if e.get("active") else "X"}</td>'
            f"<td>{_auth_cell(e)}</td>"
            f"<td>{_url_cell(e)}</td>"
            f"<td>{_status_cell(r)}</td>"
            f"<td>{_cache_link(e, by_id)}</td>"
            f'<td class="note">{html.escape(str(e.get("notes") or ""))}</td>'
            "</tr>"
        )
    body_rows = "\n".join(rows) + "\n" if rows else '      <tr><td colspan="9">catalog.json에 apis가 없습니다.</td></tr>\n'

    id_list = ", ".join(f"`{e.get('id')}`" for e in (catalog.get("apis") or []) if e.get("id"))
    if not id_list:
        id_list = "—"

    doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>api_hoard — 사용 가능 API 표</title>
<style>
  body {{ font-family: "Malgun Gothic", "Apple SD Gothic Neo", sans-serif; margin: 20px; background: #f6f7f9; color: #222; }}
  h1 {{ font-size: 1.2rem; }}
  p.meta {{ color: #555; font-size: 0.9rem; }}
  table {{ border-collapse: collapse; width: 100%; max-width: 1200px; background: #fff; box-shadow: 0 1px 3px #ccc; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 10px; text-align: left; vertical-align: top; font-size: 0.88rem; }}
  th {{ background: #1a5fb4; color: #fff; white-space: nowrap; }}
  tr:nth-child(even) {{ background: #fafafa; }}
  .ok {{ color: #0a5c0a; font-weight: 600; }}
  .skip {{ color: #6c4a00; }}
  .fail {{ color: #a40000; font-weight: 600; }}
  .note {{ max-width: 28em; line-height: 1.4; word-break: break-all; }}
  code {{ background: #eee; padding: 1px 4px; border-radius: 3px; }}
  .copy {{ max-width: 1200px; background: #fff; border: 1px solid #ccc; padding: 12px; margin-top: 20px; font-family: consolas, monospace; font-size: 0.85rem; white-space: pre-wrap; }}
  h2 {{ font-size: 1rem; margin-top: 2rem; color: #333; }}
</style>
</head>
<body>
  <h1>api_hoard — 내가 쓸 수 있는 API (표)</h1>
  <p style="background:#e3f2fd;border:1px solid #90caf9;border-radius:8px;padding:12px 14px;max-width:1200px;line-height:1.5">
    <b>이 파일은 브라우저로 열어야 표가 보입니다.</b>
    VS Code / Cursor 에서는 HTML <strong>소스</strong>만 보일 수 있어요.
    → 탐색기에서 <code>data/catalog_table.html</code> 더블클릭하거나, 같은 폴더의 <code>open_catalog_table.cmd</code> 를 실행하세요.
  </p>
  <p class="meta">manifest 갱신 시각(있을 때): {html.escape(run_utc or "아직 verify 안 함")} · <code>py -3 verify_and_store.py</code> 돌릴 때마다 이 HTML도 다시 씀.</p>
  <p class="meta"><b>쓰는 법</b> · <code>id</code> = <code>catalog.json</code>과 <code>data/last_ok/&lt;id&gt;.json</code>에 공통. 스트림/대시보드/코드에서 “어떤 스냅샷 쓰지?” 할 때 <code>id</code>만 맞추면 됨.</p>

  <table>
    <thead>
      <tr>
        <th>id</th>
        <th>이름</th>
        <th>분류</th>
        <th>ON</th>
        <th>API 키</th>
        <th>URL</th>
        <th>마지막 verify</th>
        <th>캐시</th>
        <th>메모</th>
      </tr>
    </thead>
    <tbody>
{body_rows}    </tbody>
  </table>

  <h2>AI/코드용 — catalog에 있는 id 목록</h2>
  <div class="copy">{id_list}</div>
  <p class="meta">이 표 파일: <code>api_hoard/data/catalog_table.html</code></p>
</body>
</html>
"""
    return doc


def main() -> int:
    if not CATALOG.is_file():
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
