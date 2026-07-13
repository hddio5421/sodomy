from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
from dotenv import load_dotenv

BASE_URL = "https://api.finmindtrade.com/api/v4/data"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
PRICE_DIR = RAW_DIR / "prices"
MANIFEST_PATH = RAW_DIR / "price_manifest.json"
CAPITAL_DIR = RAW_DIR / "capital"
CAPITAL_MANIFEST_PATH = RAW_DIR / "capital_manifest.json"
CAPITAL_START = "2011-12-01"
DEFAULT_START = "2000-01-01"
DEFAULT_END = "2026-07-10"


class RateLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunConfig:
    start: str
    end: str
    symbols: list[str] | None
    limit: int | None
    sleep: float
    refresh: bool
    cached_only: bool


def load_token() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
    if not token:
        raise RuntimeError("Missing FINMIND_API_KEY or FINMIND_TOKEN")
    return token


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    with MANIFEST_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_manifest(manifest: dict) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = MANIFEST_PATH.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
    temp_path.replace(MANIFEST_PATH)


def load_capital_manifest() -> dict:
    if not CAPITAL_MANIFEST_PATH.exists():
        return {}
    with CAPITAL_MANIFEST_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_capital_manifest(manifest: dict) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with CAPITAL_MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)


def manifest_covers(entry: dict | None, start: str, end: str) -> bool:
    if not entry:
        return False
    covered_through = entry.get("covered_through", entry.get("end", "0000-00-00"))
    return entry.get("start", "9999-99-99") <= start and covered_through >= end


def finmind_get(dataset: str, token: str, **params: str) -> list[dict]:
    query = {"dataset": dataset, "token": token, **params}
    response = requests.get(BASE_URL, params=query, timeout=60)
    response.encoding = "utf-8"
    payload = response.json()
    if response.status_code != 200 or payload.get("status") != 200:
        message = payload.get("msg", payload)
        if "upper limit" in str(message):
            raise RateLimitError(f"FinMind rate limit for {dataset}: {message}")
        raise RuntimeError(f"FinMind error for {dataset}: {message}")
    return payload.get("data", [])


def fetch_stock_info(token: str, refresh: bool = False) -> pd.DataFrame:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / "stock_info.csv"
    if cache.exists() and not refresh:
        return pd.read_csv(cache, dtype=str)

    rows = finmind_get("TaiwanStockInfo", token)
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("TaiwanStockInfo returned no rows")
    df.to_csv(cache, index=False, encoding="utf-8-sig")
    return df


def select_symbols(stock_info: pd.DataFrame, symbols: list[str] | None, limit: int | None) -> pd.DataFrame:
    df = stock_info.copy()
    if "stock_id" not in df.columns:
        raise RuntimeError("TaiwanStockInfo has no stock_id column")

    df["stock_id"] = df["stock_id"].astype(str)
    df = df[df["stock_id"].str.fullmatch(r"\d{4}", na=False)]

    if symbols:
        wanted = {symbol.strip() for symbol in symbols if symbol.strip()}
        df = df[df["stock_id"].isin(wanted)]

    df = df.drop_duplicates("stock_id").sort_values("stock_id")
    if limit:
        df = df.head(limit)
    return df


def read_price_cache(cache: Path) -> pd.DataFrame:
    df = pd.read_csv(cache)
    if "stock_id" in df.columns:
        df["stock_id"] = df["stock_id"].astype(str)
    return df


def next_date(date_text: str) -> str:
    return (pd.Timestamp(date_text) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def fetch_price_one(
    stock_id: str,
    token: str,
    start: str,
    end: str,
    refresh: bool,
    cached_only: bool,
    manifest: dict,
    replace_from: str | None = None,
    cycle_id: str | None = None,
) -> pd.DataFrame:
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    cache = PRICE_DIR / f"{stock_id}.csv"

    if cached_only:
        return read_price_cache(cache) if cache.exists() else pd.DataFrame()

    cached_df = read_price_cache(cache) if cache.exists() and not refresh else pd.DataFrame()
    manifest_entry = manifest.get(stock_id)
    if cache.exists() and not refresh and manifest_covers(manifest_entry, start, end):
        return cached_df

    fetch_start = max(start, replace_from) if replace_from else start
    existing_start = start
    if not replace_from and not cached_df.empty and manifest_entry:
        existing_start = min(str(manifest_entry.get("start", start)), start)
        existing_end = str(manifest_entry.get("end", "0000-00-00"))
        if existing_end >= start and existing_end < end:
            fetch_start = next_date(existing_end)

    rows = finmind_get(
        "TaiwanStockPrice",
        token,
        data_id=stock_id,
        start_date=fetch_start,
        end_date=end,
    )
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["date", "stock_id", "Trading_Volume", "Trading_money", "open", "max", "min", "close", "spread", "Trading_turnover"])
    if "stock_id" in df.columns:
        df["stock_id"] = df["stock_id"].astype(str)
    if not cached_df.empty and replace_from and "date" in cached_df.columns:
        cached_df = cached_df[cached_df["date"].astype(str) < fetch_start]
    if not cached_df.empty:
        df = pd.concat([cached_df, df], ignore_index=True)
        if "date" in df.columns:
            df = df.drop_duplicates(["date", "stock_id"], keep="last").sort_values(["stock_id", "date"])
    df.to_csv(cache, index=False, encoding="utf-8-sig")
    last_trade_date = None
    if not df.empty and "date" in df.columns:
        valid_dates = df["date"].dropna().astype(str)
        last_trade_date = valid_dates.max() if not valid_dates.empty else None
    manifest[stock_id] = {
        "start": existing_start,
        "end": end,
        "covered_through": end,
        "last_trade_date": last_trade_date,
        "cycle_id": cycle_id,
        "rows": int(len(df)),
        "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_manifest(manifest)
    return df


def fetch_prices(symbols: Iterable[str], token: str, config: RunConfig) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    symbols = list(symbols)
    manifest = load_manifest()

    for index, stock_id in enumerate(symbols, start=1):
        print(f"[{index}/{len(symbols)}] fetch {stock_id}", flush=True)
        try:
            df = fetch_price_one(stock_id, token, config.start, config.end, config.refresh, config.cached_only, manifest)
        except RateLimitError:
            raise
        except Exception as exc:
            print(f"  skip {stock_id}: {exc}", flush=True)
            continue
        if not df.empty:
            frames.append(df)
        if config.sleep > 0 and not config.cached_only:
            time.sleep(config.sleep)

    if not frames:
        raise RuntimeError("No price data downloaded")
    return pd.concat(frames, ignore_index=True)


def read_capital_cache(cache: Path) -> pd.DataFrame:
    df = pd.read_csv(cache)
    if "stock_id" in df.columns:
        df["stock_id"] = df["stock_id"].astype(str)
    return df


def fetch_capital_one(
    stock_id: str,
    token: str,
    start: str,
    end: str,
    refresh: bool,
    cached_only: bool,
    manifest: dict,
) -> pd.DataFrame:
    CAPITAL_DIR.mkdir(parents=True, exist_ok=True)
    cache = CAPITAL_DIR / f"{stock_id}.csv"

    if cached_only:
        return read_capital_cache(cache) if cache.exists() else pd.DataFrame()

    cached_df = read_capital_cache(cache) if cache.exists() and not refresh else pd.DataFrame()
    manifest_entry = manifest.get(stock_id)
    if cache.exists() and not refresh and manifest_covers(manifest_entry, start, end):
        return cached_df

    fetch_start = start
    existing_start = start
    if not cached_df.empty and manifest_entry:
        existing_start = min(str(manifest_entry.get("start", start)), start)
        existing_end = str(manifest_entry.get("end", "0000-00-00"))
        if existing_end >= start and existing_end < end:
            fetch_start = next_date(existing_end)

    rows = finmind_get(
        "TaiwanStockBalanceSheet",
        token,
        data_id=stock_id,
        start_date=fetch_start,
        end_date=end,
    )
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["date", "stock_id", "type", "value", "origin_name"])
    if "stock_id" in df.columns:
        df["stock_id"] = df["stock_id"].astype(str)
    if not cached_df.empty:
        df = pd.concat([cached_df, df], ignore_index=True)
        key_cols = [col for col in ["date", "stock_id", "type", "origin_name"] if col in df.columns]
        if key_cols:
            df = df.drop_duplicates(key_cols, keep="last").sort_values(["stock_id", "date"])
    df.to_csv(cache, index=False, encoding="utf-8-sig")
    manifest[stock_id] = {
        "start": existing_start,
        "end": end,
        "rows": int(len(df)),
        "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_capital_manifest(manifest)
    return df


def fetch_capital_history(symbols: Iterable[str], token: str, config: RunConfig) -> pd.DataFrame:
    start = max(config.start, CAPITAL_START)
    if config.end < CAPITAL_START:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    symbols = list(symbols)
    manifest = load_capital_manifest()
    for index, stock_id in enumerate(symbols, start=1):
        print(f"[{index}/{len(symbols)}] capital {stock_id}", flush=True)
        try:
            df = fetch_capital_one(stock_id, token, start, config.end, config.refresh, config.cached_only, manifest)
        except RateLimitError:
            raise
        except Exception as exc:
            print(f"  skip capital {stock_id}: {exc}", flush=True)
            continue
        if not df.empty:
            frames.append(df)
        if config.sleep > 0 and not config.cached_only:
            time.sleep(config.sleep)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def normalize_capital_history(balance_sheet: pd.DataFrame) -> pd.DataFrame:
    columns = ["stock_id", "report_date", "effective_date", "capital_billion", "capital_type", "capital_origin_name"]
    if balance_sheet.empty:
        return pd.DataFrame(columns=columns)

    df = balance_sheet.copy()
    required = {"date", "stock_id", "type", "value", "origin_name"}
    if not required.issubset(df.columns):
        return pd.DataFrame(columns=columns)

    df["stock_id"] = df["stock_id"].astype(str)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    type_text = df["type"].fillna("").astype(str)
    origin_text = df["origin_name"].fillna("").astype(str)

    exact_origins = {"股本", "股本合計", "普通股股本", "股本－普通股", "普通股"}
    exact_types = {"CapitalStock", "ShareCapital", "CommonStock", "OrdinaryShare", "OrdinaryShares", "IssuedCapital"}
    excluded = origin_text.str.contains("資本公積|股本溢價|預收股本|待分配股票股利", na=False)
    candidate = (
        origin_text.isin(exact_origins)
        | type_text.isin(exact_types)
        | (origin_text.str.contains("股本", na=False) & ~excluded)
        | type_text.str.contains("CapitalStock|ShareCapital|CommonStock|OrdinaryShare|IssuedCapital", case=False, na=False)
    )
    df = df[candidate & ~type_text.str.endswith("_per") & (df["value"] > 0) & df["date"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=columns)

    df["priority"] = 3
    df.loc[origin_text.loc[df.index].isin(exact_origins), "priority"] = 1
    df.loc[type_text.loc[df.index].isin(exact_types), "priority"] = 0
    df = df.sort_values(["stock_id", "date", "priority", "type"]).drop_duplicates(["stock_id", "date"], keep="first")

    report_date = df["date"]
    effective_date = report_date + pd.Timedelta(days=46)
    q1 = (report_date.dt.month == 3) & (report_date.dt.day == 31)
    q2 = (report_date.dt.month == 6) & (report_date.dt.day == 30)
    q3 = (report_date.dt.month == 9) & (report_date.dt.day == 30)
    q4 = (report_date.dt.month == 12) & (report_date.dt.day == 31)
    effective_date.loc[q1] = pd.to_datetime(report_date.loc[q1].dt.year.astype(str) + "-05-16")
    effective_date.loc[q2] = pd.to_datetime(report_date.loc[q2].dt.year.astype(str) + "-08-15")
    effective_date.loc[q3] = pd.to_datetime(report_date.loc[q3].dt.year.astype(str) + "-11-15")
    effective_date.loc[q4] = pd.to_datetime((report_date.loc[q4].dt.year + 1).astype(str) + "-04-01")

    result = pd.DataFrame({
        "stock_id": df["stock_id"],
        "report_date": report_date.dt.strftime("%Y-%m-%d"),
        "effective_date": effective_date.dt.strftime("%Y-%m-%d"),
        "capital_billion": df["value"] / 100_000_000,
        "capital_type": df["type"].astype(str),
        "capital_origin_name": df["origin_name"].astype(str),
    })
    return result.sort_values(["stock_id", "effective_date"])


def attach_capital_history(weekly: pd.DataFrame, capital_history: pd.DataFrame) -> pd.DataFrame:
    result = weekly.copy()
    result["capital_billion"] = pd.NA
    result["capital_report_date"] = pd.NA
    if capital_history.empty:
        return result

    left = result.copy()
    left["date_key"] = pd.to_datetime(left["date"])
    right = capital_history[["stock_id", "effective_date", "report_date", "capital_billion"]].copy()
    right["effective_key"] = pd.to_datetime(right["effective_date"])
    left = left.sort_values(["date_key", "stock_id"])
    right = right.sort_values(["effective_key", "stock_id"])
    merged = pd.merge_asof(
        left.drop(columns=["capital_billion", "capital_report_date"]),
        right.drop(columns=["effective_date"]),
        left_on="date_key",
        right_on="effective_key",
        by="stock_id",
        direction="backward",
    )
    merged = merged.rename(columns={"report_date": "capital_report_date"})
    return merged.drop(columns=["date_key", "effective_key"]).sort_values(["stock_id", "date"])


def daily_to_weekly(prices: pd.DataFrame) -> pd.DataFrame:
    df = prices.copy()
    df["stock_id"] = df["stock_id"].astype(str)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "max", "min", "close", "Trading_Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values(["stock_id", "date"])
    df = df.dropna(subset=["date", "stock_id", "open", "max", "min", "close"])

    price_cols = ["open", "max", "min", "close"]
    non_positive = (df[price_cols] <= 0).any(axis=1)
    previous_valid_close = (
        df["close"]
        .where(df["close"] > 0)
        .groupby(df["stock_id"])
        .ffill()
        .groupby(df["stock_id"])
        .shift(1)
    )
    fillable = non_positive & previous_valid_close.notna()

    if fillable.any():
        imputed = df.loc[fillable, ["date", "stock_id", *price_cols, "Trading_Volume"]].copy()
        imputed = imputed.rename(columns={col: f"original_{col}" for col in price_cols})
        imputed["filled_price"] = previous_valid_close.loc[fillable].to_numpy()
        imputed["reason"] = "non_positive_ohlc_filled_with_previous_close"
        imputed["date"] = imputed["date"].dt.strftime("%Y-%m-%d")
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        imputed.to_csv(PROCESSED_DIR / "imputed_price_rows.csv", index=False, encoding="utf-8-sig")
        for col in price_cols:
            df.loc[fillable, col] = previous_valid_close.loc[fillable]
        print(f"imputed price rows: {len(imputed)}", flush=True)

    unresolved_non_positive = (df[price_cols] <= 0).any(axis=1)
    bad_range = (df["max"] < df[["open", "min", "close"]].max(axis=1)) | (df["min"] > df[["open", "max", "close"]].min(axis=1))
    invalid_mask = unresolved_non_positive | bad_range
    invalid = df[invalid_mask].copy()
    if not invalid.empty:
        invalid["reason"] = "bad_ohlc_range"
        invalid.loc[unresolved_non_positive, "reason"] = "non_positive_ohlc_without_previous_close"
        invalid.loc[unresolved_non_positive & bad_range, "reason"] = "non_positive_ohlc_without_previous_close,bad_ohlc_range"
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        invalid["date"] = invalid["date"].dt.strftime("%Y-%m-%d")
        invalid.to_csv(PROCESSED_DIR / "invalid_price_rows.csv", index=False, encoding="utf-8-sig")
        print(f"unresolved invalid price rows: {len(invalid)}", flush=True)

    df = df[~invalid_mask]
    df["week"] = df["date"].dt.to_period("W-SAT")
    saturday_weeks = pd.Index(df.loc[df["date"].dt.dayofweek == 5, "week"].unique())

    weekly = (
        df.groupby(["stock_id", "week"], as_index=False)
        .agg(
            last_trade_date=("date", "max"),
            open=("open", "first"),
            high=("max", "max"),
            low=("min", "min"),
            close=("close", "last"),
            volume=("Trading_Volume", "sum"),
        )
    )
    weekly["week_end_date"] = weekly["week"].dt.end_time.dt.normalize()
    friday_weeks = ~weekly["week"].isin(saturday_weeks)
    weekly.loc[friday_weeks, "week_end_date"] = weekly.loc[friday_weeks, "week_end_date"] - pd.Timedelta(days=1)
    weekly["date"] = weekly["week"].dt.end_time.dt.normalize() - pd.Timedelta(days=5)
    weekly = weekly.sort_values(["stock_id", "date"])
    weekly["date"] = weekly["date"].dt.strftime("%Y-%m-%d")
    weekly["week_end_date"] = weekly["week_end_date"].dt.strftime("%Y-%m-%d")
    weekly["last_trade_date"] = weekly["last_trade_date"].dt.strftime("%Y-%m-%d")
    return weekly.drop(columns=["week"])


def add_indicators(weekly: pd.DataFrame) -> pd.DataFrame:
    df = weekly.copy().sort_values(["stock_id", "date"])
    df["ma20"] = df.groupby("stock_id")["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["prev_close"] = df.groupby("stock_id")["close"].shift(1)
    df["prev_ma20"] = df.groupby("stock_id")["ma20"].shift(1)
    df["cross_above_ma20"] = (df["close"] > df["ma20"]) & (df["prev_close"] <= df["prev_ma20"])
    df["ma20_rising"] = df["ma20"] > df["prev_ma20"]
    df["ma20_distance_pct"] = (df["close"] / df["ma20"] - 1.0) * 100
    return df


def build_signals(weekly: pd.DataFrame, stock_info: pd.DataFrame) -> pd.DataFrame:
    signals = weekly[weekly["cross_above_ma20"]].copy()
    signals["stock_id"] = signals["stock_id"].astype(str)
    stock_info = stock_info.copy()
    stock_info["stock_id"] = stock_info["stock_id"].astype(str)
    info_cols = [col for col in ["stock_id", "stock_name", "industry_category", "type"] if col in stock_info.columns]
    if info_cols:
        info = stock_info[info_cols].drop_duplicates("stock_id")
        signals = signals.merge(info, on="stock_id", how="left")
    return signals.sort_values(["date", "stock_id"])


def dataframe_records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", force_ascii=False))


def build_chart_payloads(
    weekly: pd.DataFrame,
    signals: pd.DataFrame,
    stock_info: pd.DataFrame,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    finalized_week_through: str | None = None,
) -> tuple[dict, dict[str, list[dict]], dict[str, list[dict]]]:
    weekly = weekly.copy()
    signals = signals.copy()
    stock_info = stock_info.copy()
    weekly["stock_id"] = weekly["stock_id"].astype(str)
    signals["stock_id"] = signals["stock_id"].astype(str)
    stock_info["stock_id"] = stock_info["stock_id"].astype(str)
    series_ids = sorted(weekly["stock_id"].dropna().astype(str).unique())

    info_cols = [col for col in ["stock_id", "stock_name", "industry_category", "type"] if col in stock_info.columns]
    meta = {}
    if info_cols and series_ids:
        info = stock_info[stock_info["stock_id"].astype(str).isin(series_ids)]
        for row in dataframe_records(info[info_cols].drop_duplicates("stock_id")):
            meta[str(row["stock_id"])] = row

    series = {}
    keep_cols = [
        "date", "open", "high", "low", "close", "volume", "ma20", "cross_above_ma20",
        "ma20_rising", "ma20_distance_pct", "capital_billion", "capital_report_date",
    ]
    for stock_id, group in weekly.groupby("stock_id"):
        series[str(stock_id)] = dataframe_records(group[keep_cols])

    signal_dates = sorted(signals["date"].dropna().astype(str).unique())
    index = {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start": start,
        "end": end,
        "data_through": end,
        "finalized_week_through": finalized_week_through or end,
        "dates": signal_dates,
        "meta": meta,
        "series_files": {stock_id: f"series/{stock_id}.json" for stock_id in series},
        "signal_files": {date: f"signals/{date}.json" for date in signal_dates},
    }
    signal_groups = {
        date: dataframe_records(group.drop(columns=[]))
        for date, group in signals.groupby("date", sort=True)
    }
    return index, series, signal_groups


def build_outputs(
    prices: pd.DataFrame,
    stock_info: pd.DataFrame,
    balance_sheet: pd.DataFrame | None = None,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    finalized_week_through: str | None = None,
) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    weekly = add_indicators(daily_to_weekly(prices))
    capital_history = normalize_capital_history(balance_sheet if balance_sheet is not None else pd.DataFrame())
    capital_cache = PROCESSED_DIR / "capital_history.csv"
    if capital_history.empty and capital_cache.exists():
        capital_history = pd.read_csv(capital_cache, dtype={"stock_id": str})
        print(f"using normalized capital cache: {capital_cache}", flush=True)
    weekly = attach_capital_history(weekly, capital_history)
    signals = build_signals(weekly, stock_info)
    chart_index, series, signal_groups = build_chart_payloads(
        weekly,
        signals,
        stock_info,
        start=start,
        end=end,
        finalized_week_through=finalized_week_through,
    )

    weekly.to_csv(PROCESSED_DIR / "weekly.csv", index=False, encoding="utf-8-sig")
    signals.to_csv(PROCESSED_DIR / "signals.csv", index=False, encoding="utf-8-sig")
    capital_history.to_csv(PROCESSED_DIR / "capital_history.csv", index=False, encoding="utf-8-sig")

    series_dir = PROCESSED_DIR / "series"
    series_dir.mkdir(parents=True, exist_ok=True)
    for stock_id, records in series.items():
        with (series_dir / f"{stock_id}.json").open("w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    signals_dir = PROCESSED_DIR / "signals"
    signals_dir.mkdir(parents=True, exist_ok=True)
    for date, records in signal_groups.items():
        with (signals_dir / f"{date}.json").open("w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    with (PROCESSED_DIR / "chart_index.json").open("w", encoding="utf-8") as fh:
        json.dump(chart_index, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    print(f"weekly rows: {len(weekly)}", flush=True)
    print(f"signals: {len(signals)}", flush=True)
    print(f"capital records: {len(capital_history)}", flush=True)
    print(f"series files: {len(series)}", flush=True)
    print(f"output: {PROCESSED_DIR / 'chart_index.json'}", flush=True)


def run(config: RunConfig) -> None:
    token = load_token()
    stock_info = fetch_stock_info(token, refresh=config.refresh)
    selected = select_symbols(stock_info, config.symbols, config.limit)
    if selected.empty:
        raise RuntimeError("No symbols selected")

    print(f"selected symbols: {len(selected)}", flush=True)
    prices = fetch_prices(selected["stock_id"].tolist(), token, config)
    balance_sheet = fetch_capital_history(selected["stock_id"].tolist(), token, config)
    build_outputs(prices, stock_info, balance_sheet, start=config.start, end=config.end)


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(description="Download Taiwan stock data from FinMind and build weekly MA20 signals.")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--symbols", help="Comma-separated stock ids, e.g. 2330,2317. Omit to fetch all 4-digit stocks.")
    parser.add_argument("--limit", type=int, help="Limit symbols for testing.")
    parser.add_argument("--sleep", type=float, default=0.15, help="Seconds to sleep between API calls.")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached CSV files and re-download.")
    parser.add_argument("--cached-only", action="store_true", help="Build outputs from cached price CSV files without calling FinMind.")
    args = parser.parse_args()
    symbols = [item.strip() for item in args.symbols.split(",")] if args.symbols else None
    return RunConfig(args.start, args.end, symbols, args.limit, args.sleep, args.refresh, args.cached_only)


if __name__ == "__main__":
    run(parse_args())


