"""
yfinance 1.3+ 는 peewee SQLite(WAL) 캐시를 씀. 손상 시
DatabaseError('database disk image is malformed') 가 모든 심볼에서 반복됨.

대응 (기본):
  스캔 시작 시 **임시 폴더**로 tz/cookie/ISIN 캐시 위치를 바꿔 사용자 프로필 캐시를 우회.
  (set_tz_cache_location 은 첫 티커 조회 전에 호출해야 함)

환경 변수:
  YFIN_USE_DEFAULT_SESSION_CACHE=1
      임시 폴더 대신 기본 %LocalAppData%\\py-yfinance 사용 + 아래 파일 복구만 수행
  YFIN_SKIP_CACHE_REPAIR=1
      이 모듈에서 아무 것도 하지 않음
  YFIN_VERBOSE_CACHE_REPAIR=1
      캐시 경로/삭제 로그
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys


def _yfinance_official_cache_dir() -> str:
    """yfinance.cache 와 동일: join(user_cache_dir(), 'py-yfinance')."""
    try:
        from platformdirs import user_cache_dir

        return os.path.join(user_cache_dir(), "py-yfinance")
    except Exception:
        la = (os.environ.get("LOCALAPPDATA") or "").strip()
        return os.path.join(la, "py-yfinance") if la else ""


def _cache_roots() -> list[str]:
    roots = [_yfinance_official_cache_dir()]
    try:
        from platformdirs import user_cache_dir

        roots.append(user_cache_dir("py-yfinance"))
    except Exception:
        pass
    la = (os.environ.get("LOCALAPPDATA") or "").strip()
    if la:
        roots.append(os.path.join(la, "py-yfinance"))
    roots.append(os.path.join(os.path.expanduser("~"), ".cache", "py-yfinance"))
    seen: set[str] = set()
    out: list[str] = []
    for p in roots:
        if not p:
            continue
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        if os.path.isdir(ap):
            out.append(ap)
    return out


def _unlink_quiet(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def _strip_sqlite_wal_shm(cache_dir: str) -> int:
    """WAL/SHM 만 꼬인 경우 메인 db 는 살릴 수 있음."""
    n = 0
    if not os.path.isdir(cache_dir):
        return 0
    for name in os.listdir(cache_dir):
        if name.endswith("-wal") or name.endswith("-shm"):
            if _unlink_quiet(os.path.join(cache_dir, name)):
                n += 1
    return n


def _sqlite_paths_under(root: str) -> list[str]:
    found: list[str] = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            low = f.lower()
            if low.endswith((".sqlite", ".sqlite3", ".db")) and not low.endswith(("-wal", "-shm")):
                found.append(os.path.join(dirpath, f))
    return found


def _is_sqlite_corrupt(path: str) -> bool:
    try:
        con = sqlite3.connect(path, timeout=0.5)
        try:
            q = con.execute("PRAGMA quick_check").fetchall()
            if q and q[0][0] not in ("ok", "OK", "ok"):
                return True
        finally:
            con.close()
    except sqlite3.Error:
        return True
    except OSError:
        return True
    return False


def _nuke_entire_dir(path: str, verbose: bool) -> int:
    if not os.path.isdir(path):
        return 0
    try:
        shutil.rmtree(path)
        if verbose:
            print(f"[yfinance] 캐시 폴더 전체 삭제: {path}", file=sys.stderr)
        return 1
    except OSError:
        return 0


def repair_yfinance_cache_once() -> int:
    """손상 SQLite 제거 + WAL/SHM 정리. 반환: 삭제한 db 파일 수."""
    if os.environ.get("YFIN_SKIP_CACHE_REPAIR", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return 0
    verbose = os.environ.get("YFIN_VERBOSE_CACHE_REPAIR", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    removed = 0
    if os.environ.get("YFIN_NUKE_PY_YFINANCE_DIR", "").strip().lower() in ("1", "true", "yes"):
        d = _yfinance_official_cache_dir()
        if d and os.path.isdir(d):
            _nuke_entire_dir(d, verbose)
        return 0

    for root in _cache_roots():
        stripped = _strip_sqlite_wal_shm(root)
        if stripped and verbose:
            print(f"[yfinance] WAL/SHM 제거 {stripped}개: {root}", file=sys.stderr)
        for path in _sqlite_paths_under(root):
            if not _is_sqlite_corrupt(path):
                continue
            base = path
            _unlink_quiet(base + "-wal")
            _unlink_quiet(base + "-shm")
            if _unlink_quiet(path):
                removed += 1
                if verbose:
                    print(f"[yfinance] 손상 DB 삭제: {path}", file=sys.stderr)
    return removed


def try_repair_with_message() -> int:
    """
    export 스캔 직전 호출. 기본은 임시 캐시로 우회(가장 안정적).
    반환: 삭제한 db 수(임시 우회만 한 경우 0).
    """
    if os.environ.get("YFIN_SKIP_CACHE_REPAIR", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return 0
    verbose = os.environ.get("YFIN_VERBOSE_CACHE_REPAIR", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    use_persistent = os.environ.get("YFIN_USE_DEFAULT_SESSION_CACHE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    if not use_persistent:
        try:
            import tempfile

            import yfinance as yf

            td = tempfile.mkdtemp(prefix="yfin-export-cache-")
            yf.set_tz_cache_location(td)
            if verbose:
                print(f"  [yfinance] 이번 실행 캐시(임시): {td}", flush=True)
            return 0
        except Exception as ex:
            print(
                f"  [yfinance] 임시 캐시 전환 실패, 프로필 캐시 복구 시도: {ex}",
                flush=True,
            )

    n_strip = 0
    for root in _cache_roots():
        n_strip += _strip_sqlite_wal_shm(root)
    if n_strip and verbose:
        print(f"  [yfinance] WAL/SHM 파일 {n_strip}개 제거", flush=True)

    n = repair_yfinance_cache_once()
    if n:
        print(
            f"  [yfinance] 손상된 SQLite 캐시 {n}개 삭제함.",
            flush=True,
        )
    return n
