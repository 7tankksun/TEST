"""
run_all_exports.cmd 전용: run_local_export.py 를 실행하면서
같은 내용을 콘솔(한 줄씩) + UTF-8 로그 파일에 동시에 기록합니다.
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: (배치에서) py -3 tee_export.py <logfile>", file=sys.stderr)
        return 2
    logp = os.path.abspath(sys.argv[1])
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONUNBUFFERED"] = "1"

    p = subprocess.Popen(
        [sys.executable, "-u", "run_local_export.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=os.getcwd(),
    )
    if not p.stdout:
        return 1
    with open(logp, "a", encoding="utf-8", newline="") as f:
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            f.write(line)
    return int(p.wait())


if __name__ == "__main__":
    raise SystemExit(main())
