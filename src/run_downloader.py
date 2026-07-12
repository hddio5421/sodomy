from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "finmind_downloader.log"


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run_once(start: str, end: str, sleep: float) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "src" / "pipeline.py"),
        "--start",
        start,
        "--end",
        end,
        "--sleep",
        str(sleep),
    ]
    log("running: " + " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output_lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        output_lines.append(line)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(line, flush=True)
    return proc.wait(), "\n".join(output_lines[-80:])


def rebuild_cached_outputs(start: str, end: str) -> None:
    cmd = [sys.executable, str(PROJECT_ROOT / "src" / "pipeline.py"), "--start", start, "--end", end, "--cached-only", "--sleep", "0"]
    log("rebuilding cached outputs")
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Keep downloading FinMind data and resume after API rate limits.")
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--end", default="2026-07-10")
    parser.add_argument("--retry-minutes", type=float, default=65)
    parser.add_argument("--sleep", type=float, default=0.15)
    args = parser.parse_args()

    wait_seconds = int(args.retry_minutes * 60)
    log(f"scheduler started, range={args.start}..{args.end}, retry={args.retry_minutes} minutes")

    while True:
        code, tail = run_once(args.start, args.end, args.sleep)
        rebuild_cached_outputs(args.start, args.end)
        if code == 0:
            log("download completed")
            return
        if "upper limit" in tail or "rate limit" in tail.lower():
            log(f"FinMind API limit reached; sleeping {args.retry_minutes} minutes before retry")
            time.sleep(wait_seconds)
            continue
        log(f"pipeline failed with exit code {code}; sleeping {args.retry_minutes} minutes before retry")
        time.sleep(wait_seconds)


if __name__ == "__main__":
    main()
