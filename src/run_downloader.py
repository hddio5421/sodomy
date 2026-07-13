from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "finmind_downloader.log"
STATE_FILE = pipeline.RAW_DIR / "incremental_update_state.json"
LOCK_FILE = pipeline.RAW_DIR / "incremental_update.lock"
TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_BATCH_SIZE = 550
MAX_BATCH_SIZE = 550


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(TAIPEI):%Y-%m-%d %H:%M:%S}] {message}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def date_text(value: date) -> str:
    return value.isoformat()


def friday_on_or_before(value: date) -> date:
    return value - timedelta(days=(value.weekday() - 4) % 7)


def automatic_target(as_of: date) -> date:
    # Weekend runs publish through the Friday that just ended. Weekday runs are
    # explicitly partial and stop at today; a future Friday is never requested.
    return friday_on_or_before(as_of) if as_of.weekday() >= 5 else as_of


def finalized_friday(target: date, as_of: date) -> date:
    candidate = friday_on_or_before(target)
    # A run performed on Friday may occur before FinMind has published the full
    # trading day. It becomes official only from Saturday onward.
    if candidate >= as_of:
        candidate -= timedelta(days=7)
    return candidate


def next_week_monday(finalized: date) -> date:
    return finalized + timedelta(days=3)


def target_already_completed(state: dict, target: date, as_of: date) -> bool:
    completed_target = str(state.get("last_completed_target", "0000-00-00"))
    finalized = parse_date(str(state["finalized_week_through"]))
    return completed_target >= date_text(target) and finalized >= finalized_friday(target, as_of)


def entry_coverage(entry: dict | None) -> str:
    if not entry:
        return "0000-00-00"
    return str(entry.get("covered_through", entry.get("end", "0000-00-00")))


def cycle_entry_complete(entry: dict | None, cycle: dict) -> bool:
    cycle_id = cycle.get("id")
    if cycle_id:
        return bool(entry and entry.get("cycle_id") == cycle_id)
    return entry_coverage(entry) >= str(cycle["target_end"])


def has_full_price_base(manifest: dict, stock_ids: list[str]) -> bool:
    return bool(stock_ids) and all(
        (pipeline.PRICE_DIR / f"{stock_id}.csv").exists()
        and str(manifest.get(stock_id, {}).get("start", "9999-99-99")) <= pipeline.DEFAULT_START
        for stock_id in stock_ids
    )


def infer_finalized_week(manifest: dict, as_of: date) -> date:
    coverage = [entry_coverage(entry) for entry in manifest.values() if entry_coverage(entry) != "0000-00-00"]
    if not coverage:
        return friday_on_or_before(as_of - timedelta(days=7))
    earliest_common_coverage = parse_date(min(coverage))
    candidate = friday_on_or_before(earliest_common_coverage)
    if candidate >= as_of:
        candidate -= timedelta(days=7)
    return candidate


def load_state(manifest: dict, as_of: date) -> dict:
    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as fh:
            state = json.load(fh)
        state.setdefault("version", 1)
        state.setdefault("cycle", None)
        state.setdefault("finalized_week_through", date_text(infer_finalized_week(manifest, as_of)))
        return state
    return {
        "version": 1,
        "finalized_week_through": date_text(infer_finalized_week(manifest, as_of)),
        "cycle": None,
    }


def save_state(state: dict) -> None:
    pipeline.RAW_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = STATE_FILE.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
    temp_path.replace(STATE_FILE)


def acquire_lock() -> bool:
    pipeline.RAW_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        age = datetime.now().timestamp() - LOCK_FILE.stat().st_mtime
        if age < 4 * 60 * 60:
            log(f"another incremental update is still active; lock={LOCK_FILE}")
            return False
        log("removing stale incremental update lock older than 4 hours")
        LOCK_FILE.unlink(missing_ok=True)
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        log("another incremental update acquired the lock")
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"pid": os.getpid(), "started_at": datetime.now(TAIPEI).isoformat()}))
    return True


def release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


def rebuild_outputs(target: str, finalized: str, stock_info, stock_ids: list[str], token: str) -> None:
    config = pipeline.RunConfig(
        start=pipeline.DEFAULT_START,
        end=target,
        symbols=None,
        limit=None,
        sleep=0,
        refresh=False,
        cached_only=True,
    )
    log("all price batches complete; rebuilding weekly K, MA20, signals and web data from cache")
    prices = pipeline.fetch_prices(stock_ids, token, config)
    balance_sheet = pipeline.fetch_capital_history(stock_ids, token, config)
    pipeline.build_outputs(
        prices,
        stock_info,
        balance_sheet,
        start=pipeline.DEFAULT_START,
        end=target,
        finalized_week_through=finalized,
    )


def status_text(state: dict, manifest: dict, total: int) -> str:
    cycle = state.get("cycle")
    if not cycle:
        return f"idle; finalized_week_through={state['finalized_week_through']}; stocks={total}"
    target = str(cycle["target_end"])
    remaining = sum(not cycle_entry_complete(manifest.get(stock_id), cycle) for stock_id in cycle.get("stock_ids", []))
    return (
        f"target={target}; replace_from={cycle['replace_from']}; "
        f"completed={total - remaining}/{total}; remaining={remaining}; "
        f"finalized_week_through={state['finalized_week_through']}"
    )


def execute(args: argparse.Namespace) -> int:
    as_of = datetime.now(TAIPEI).date()
    manifest = pipeline.load_manifest()
    state = load_state(manifest, as_of)
    report = print if args.dry_run else log

    stock_cache = pipeline.RAW_DIR / "stock_info.csv"
    if args.status or args.dry_run:
        if not stock_cache.exists():
            raise RuntimeError("Missing data/raw/stock_info.csv; run the full pipeline once first")
        stock_info = pipeline.select_symbols(pd.read_csv(stock_cache, dtype=str), None, None)
    else:
        token = pipeline.load_token()
        stock_info = pipeline.select_symbols(pipeline.fetch_stock_info(token), None, None)
    stock_ids = stock_info["stock_id"].astype(str).tolist()

    if args.status:
        print(status_text(state, manifest, len(stock_ids)))
        return 0

    cycle = state.get("cycle")
    if cycle:
        target = parse_date(str(cycle["target_end"]))
        replace_from = parse_date(str(cycle["replace_from"]))
        report(f"resuming locked cycle target={target}; replace_from={replace_from}")
    else:
        target = automatic_target(as_of) if args.end == "auto" else parse_date(args.end)
        if target > as_of:
            raise ValueError(f"end date {target} is in the future; latest allowed date is {as_of}")
        finalized = parse_date(str(state["finalized_week_through"]))
        if target_already_completed(state, target, as_of):
            report(
                f"target already completed; target={target}, "
                f"finalized_week_through={finalized}"
            )
            return 0
        bootstrap = not has_full_price_base(manifest, stock_ids)
        replace_from = parse_date(pipeline.DEFAULT_START) if bootstrap else next_week_monday(finalized)
        if target < replace_from:
            report(f"no new dates to download; target={target}, finalized={finalized}")
            return 0
        cycle = {
            "id": uuid4().hex,
            "target_end": date_text(target),
            "replace_from": date_text(replace_from),
            "stock_ids": stock_ids,
            "bootstrap": bootstrap,
            "created_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        }
        state["cycle"] = cycle
        if not args.dry_run:
            save_state(state)
        mode = "full GitHub/bootstrap history" if bootstrap else "current/unfinalized week"
        report(f"new cycle target={target}; replace {mode} from {replace_from}")

    cycle_stock_ids = [str(item) for item in cycle.get("stock_ids", stock_ids)]
    pending = [stock_id for stock_id in cycle_stock_ids if not cycle_entry_complete(manifest.get(stock_id), cycle)]
    batch = pending[: args.batch_size]
    report(
        f"batch plan size={len(batch)} (max={args.batch_size}); "
        f"completed={len(cycle_stock_ids) - len(pending)}/{len(cycle_stock_ids)}; remaining_before={len(pending)}"
    )
    if args.dry_run:
        preview = ",".join(batch[:10])
        print(f"dry-run next symbols: {preview}{'...' if len(batch) > 10 else ''}")
        return 0

    rate_limited = False
    errors = 0
    for index, stock_id in enumerate(batch, start=1):
        print(f"[{index}/{len(batch)}] incremental price {stock_id}", flush=True)
        try:
            pipeline.fetch_price_one(
                stock_id,
                token,
                pipeline.DEFAULT_START,
                date_text(target),
                refresh=False,
                cached_only=False,
                manifest=manifest,
                replace_from=date_text(replace_from),
                cycle_id=cycle.get("id"),
            )
        except pipeline.RateLimitError as exc:
            log(f"FinMind limit reached after {index - 1} completed requests: {exc}")
            rate_limited = True
            break
        except Exception as exc:
            errors += 1
            log(f"stock {stock_id} failed and will retry next schedule: {exc}")
        if args.sleep > 0:
            time.sleep(args.sleep)

    manifest = pipeline.load_manifest()
    remaining = [stock_id for stock_id in cycle_stock_ids if not cycle_entry_complete(manifest.get(stock_id), cycle)]
    state["cycle"]["remaining"] = len(remaining)
    state["cycle"]["updated_at"] = datetime.now(TAIPEI).isoformat(timespec="seconds")
    save_state(state)

    if remaining:
        log(
            f"batch finished; target={target}; completed={len(cycle_stock_ids) - len(remaining)}/"
            f"{len(cycle_stock_ids)}; remaining={len(remaining)}; errors={errors}; rate_limited={rate_limited}"
        )
        return 0

    finalized = finalized_friday(target, as_of)
    finalized_text = max(state["finalized_week_through"], date_text(finalized))
    rebuild_outputs(date_text(target), finalized_text, stock_info, cycle_stock_ids, token)
    state["finalized_week_through"] = finalized_text
    state["last_completed_target"] = date_text(target)
    state["last_completed_at"] = datetime.now(TAIPEI).isoformat(timespec="seconds")
    state["cycle"] = None
    save_state(state)
    log(f"incremental cycle complete; data_through={target}; finalized_week_through={finalized_text}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one resumable FinMind price batch, then rebuild outputs after all stocks reach the locked target."
    )
    parser.add_argument("--end", default="auto", help="YYYY-MM-DD or auto; auto uses today on weekdays and Friday on weekends")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--status", action="store_true", help="Show saved progress without downloading")
    parser.add_argument("--dry-run", action="store_true", help="Show the next batch without writing state or calling FinMind")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        parser.error(f"--batch-size must be between 1 and {MAX_BATCH_SIZE}")
    if args.sleep < 0:
        parser.error("--sleep must be non-negative")
    return args


def main() -> int:
    args = parse_args()
    if args.status or args.dry_run:
        return execute(args)
    if not acquire_lock():
        return 0
    try:
        return execute(args)
    finally:
        release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
