"""Build annual price-threshold hour reports for EU countries plus the UK."""

from __future__ import annotations

import argparse
import os
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from bess_pipeline.client import EnergyChartsClient, EnergyChartsClientConfig
from bess_pipeline.storage import ensure_data_dirs

ENTSOE_API_URL = "https://web-api.tp.entsoe.eu/api"
DEFAULT_START_YEAR = 2016
DEFAULT_OUTPUT_DIR = Path("data/processed")
REPORT_TIMEZONE = "Europe/Zurich"


@dataclass(frozen=True)
class ReportCountry:
    code: str
    name: str


@dataclass(frozen=True)
class PriceZone:
    code: str
    label: str
    country_codes: tuple[str, ...]
    energy_charts_bzn: str | None = None
    entsoe_eic: str | None = None
    license_note: str = ""


EU_COUNTRIES_PLUS_UK: tuple[ReportCountry, ...] = (
    ReportCountry("AT", "Austria"),
    ReportCountry("BE", "Belgium"),
    ReportCountry("BG", "Bulgaria"),
    ReportCountry("HR", "Croatia"),
    ReportCountry("CY", "Cyprus"),
    ReportCountry("CZ", "Czech Republic"),
    ReportCountry("DK", "Denmark"),
    ReportCountry("EE", "Estonia"),
    ReportCountry("FI", "Finland"),
    ReportCountry("FR", "France"),
    ReportCountry("DE", "Germany"),
    ReportCountry("GR", "Greece"),
    ReportCountry("HU", "Hungary"),
    ReportCountry("IE", "Ireland"),
    ReportCountry("IT", "Italy"),
    ReportCountry("LV", "Latvia"),
    ReportCountry("LT", "Lithuania"),
    ReportCountry("LU", "Luxembourg"),
    ReportCountry("MT", "Malta"),
    ReportCountry("NL", "Netherlands"),
    ReportCountry("PL", "Poland"),
    ReportCountry("PT", "Portugal"),
    ReportCountry("RO", "Romania"),
    ReportCountry("SK", "Slovakia"),
    ReportCountry("SI", "Slovenia"),
    ReportCountry("ES", "Spain"),
    ReportCountry("SE", "Sweden"),
    ReportCountry("UK", "United Kingdom"),
)

COUNTRIES_BY_CODE = {country.code: country for country in EU_COUNTRIES_PLUS_UK}

ENERGY_CHARTS_PUBLIC_LICENSE = "CC BY 4.0 via Energy-Charts / SMARD where applicable"
ENERGY_CHARTS_RESTRICTED_LICENSE = (
    "Energy-Charts marks this bidding-zone price data as private/internal-use only"
)
ENTSOE_LICENSE = "ENTSO-E Transparency Platform; review platform terms before reuse"

ENERGY_CHARTS_ZONES: tuple[PriceZone, ...] = (
    PriceZone("AT", "Austria", ("AT",), "AT", license_note=ENERGY_CHARTS_PUBLIC_LICENSE),
    PriceZone("BE", "Belgium", ("BE",), "BE", license_note=ENERGY_CHARTS_PUBLIC_LICENSE),
    PriceZone("BG", "Bulgaria", ("BG",), "BG", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
    PriceZone("HR", "Croatia", ("HR",), "HR", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
    PriceZone("CZ", "Czech Republic", ("CZ",), "CZ", license_note=ENERGY_CHARTS_PUBLIC_LICENSE),
    PriceZone("DK1", "Denmark 1", ("DK",), "DK1", license_note=ENERGY_CHARTS_PUBLIC_LICENSE),
    PriceZone("DK2", "Denmark 2", ("DK",), "DK2", license_note=ENERGY_CHARTS_PUBLIC_LICENSE),
    PriceZone("EE", "Estonia", ("EE",), "EE", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
    PriceZone("FI", "Finland", ("FI",), "FI", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
    PriceZone("FR", "France", ("FR",), "FR", license_note=ENERGY_CHARTS_PUBLIC_LICENSE),
    PriceZone(
        "DE-AT-LU",
        "Germany / Austria / Luxembourg historical",
        ("DE", "AT", "LU"),
        "DE-AT-LU",
        license_note=ENERGY_CHARTS_PUBLIC_LICENSE,
    ),
    PriceZone(
        "DE-LU",
        "Germany / Luxembourg",
        ("DE", "LU"),
        "DE-LU",
        license_note=ENERGY_CHARTS_PUBLIC_LICENSE,
    ),
    PriceZone("GR", "Greece", ("GR",), "GR", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
    PriceZone("HU", "Hungary", ("HU",), "HU", license_note=ENERGY_CHARTS_PUBLIC_LICENSE),
    PriceZone(
        "IT-Calabria",
        "Italy Calabria",
        ("IT",),
        "IT-Calabria",
        license_note=ENERGY_CHARTS_RESTRICTED_LICENSE,
    ),
    PriceZone(
        "IT-Centre-North",
        "Italy Centre North",
        ("IT",),
        "IT-Centre-North",
        license_note=ENERGY_CHARTS_RESTRICTED_LICENSE,
    ),
    PriceZone(
        "IT-Centre-South",
        "Italy Centre South",
        ("IT",),
        "IT-Centre-South",
        license_note=ENERGY_CHARTS_RESTRICTED_LICENSE,
    ),
    PriceZone(
        "IT-North",
        "Italy North",
        ("IT",),
        "IT-North",
        license_note=ENERGY_CHARTS_PUBLIC_LICENSE,
    ),
    PriceZone(
        "IT-SACOAC",
        "Italy Sardinia Corsica AC",
        ("IT",),
        "IT-SACOAC",
        license_note=ENERGY_CHARTS_RESTRICTED_LICENSE,
    ),
    PriceZone(
        "IT-SACODC",
        "Italy Sardinia Corsica DC",
        ("IT",),
        "IT-SACODC",
        license_note=ENERGY_CHARTS_RESTRICTED_LICENSE,
    ),
    PriceZone(
        "IT-Sardinia",
        "Italy Sardinia",
        ("IT",),
        "IT-Sardinia",
        license_note=ENERGY_CHARTS_RESTRICTED_LICENSE,
    ),
    PriceZone(
        "IT-Sicily",
        "Italy Sicily",
        ("IT",),
        "IT-Sicily",
        license_note=ENERGY_CHARTS_RESTRICTED_LICENSE,
    ),
    PriceZone(
        "IT-South",
        "Italy South",
        ("IT",),
        "IT-South",
        license_note=ENERGY_CHARTS_RESTRICTED_LICENSE,
    ),
    PriceZone("LT", "Lithuania", ("LT",), "LT", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
    PriceZone("LV", "Latvia", ("LV",), "LV", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
    PriceZone("NL", "Netherlands", ("NL",), "NL", license_note=ENERGY_CHARTS_PUBLIC_LICENSE),
    PriceZone("PL", "Poland", ("PL",), "PL", license_note=ENERGY_CHARTS_PUBLIC_LICENSE),
    PriceZone("PT", "Portugal", ("PT",), "PT", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
    PriceZone("RO", "Romania", ("RO",), "RO", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
    PriceZone("SE1", "Sweden 1", ("SE",), "SE1", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
    PriceZone("SE2", "Sweden 2", ("SE",), "SE2", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
    PriceZone("SE3", "Sweden 3", ("SE",), "SE3", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
    PriceZone("SE4", "Sweden 4", ("SE",), "SE4", license_note=ENERGY_CHARTS_PUBLIC_LICENSE),
    PriceZone("SI", "Slovenia", ("SI",), "SI", license_note=ENERGY_CHARTS_PUBLIC_LICENSE),
    PriceZone("SK", "Slovakia", ("SK",), "SK", license_note=ENERGY_CHARTS_RESTRICTED_LICENSE),
)

ENTSOE_ZONES: tuple[PriceZone, ...] = (
    PriceZone("AT", "Austria", ("AT",), entsoe_eic="10YAT-APG------L", license_note=ENTSOE_LICENSE),
    PriceZone("BE", "Belgium", ("BE",), entsoe_eic="10YBE----------2", license_note=ENTSOE_LICENSE),
    PriceZone(
        "BG", "Bulgaria", ("BG",), entsoe_eic="10YCA-BULGARIA-R", license_note=ENTSOE_LICENSE
    ),
    PriceZone("HR", "Croatia", ("HR",), entsoe_eic="10YHR-HEP------M", license_note=ENTSOE_LICENSE),
    PriceZone("CY", "Cyprus", ("CY",), entsoe_eic="10YCY-1001A0003J", license_note=ENTSOE_LICENSE),
    PriceZone(
        "CZ", "Czech Republic", ("CZ",), entsoe_eic="10YCZ-CEPS-----N", license_note=ENTSOE_LICENSE
    ),
    PriceZone(
        "DK1", "Denmark 1", ("DK",), entsoe_eic="10YDK-1--------W", license_note=ENTSOE_LICENSE
    ),
    PriceZone(
        "DK2", "Denmark 2", ("DK",), entsoe_eic="10YDK-2--------M", license_note=ENTSOE_LICENSE
    ),
    PriceZone("EE", "Estonia", ("EE",), entsoe_eic="10Y1001A1001A39I", license_note=ENTSOE_LICENSE),
    PriceZone("FI", "Finland", ("FI",), entsoe_eic="10YFI-1--------U", license_note=ENTSOE_LICENSE),
    PriceZone("FR", "France", ("FR",), entsoe_eic="10YFR-RTE------C", license_note=ENTSOE_LICENSE),
    PriceZone(
        "DE-AT-LU",
        "Germany / Austria / Luxembourg historical",
        ("DE", "AT", "LU"),
        entsoe_eic="10Y1001A1001A63L",
        license_note=ENTSOE_LICENSE,
    ),
    PriceZone(
        "DE-LU",
        "Germany / Luxembourg",
        ("DE", "LU"),
        entsoe_eic="10Y1001A1001A82H",
        license_note=ENTSOE_LICENSE,
    ),
    PriceZone("GR", "Greece", ("GR",), entsoe_eic="10YGR-HTSO-----Y", license_note=ENTSOE_LICENSE),
    PriceZone("HU", "Hungary", ("HU",), entsoe_eic="10YHU-MAVIR----U", license_note=ENTSOE_LICENSE),
    PriceZone(
        "IE-SEM", "Ireland SEM", ("IE",), entsoe_eic="10Y1001A1001A59C", license_note=ENTSOE_LICENSE
    ),
    PriceZone(
        "IT-Calabria",
        "Italy Calabria",
        ("IT",),
        entsoe_eic="10Y1001C--00096J",
        license_note=ENTSOE_LICENSE,
    ),
    PriceZone(
        "IT-Centre-North",
        "Italy Centre North",
        ("IT",),
        entsoe_eic="10Y1001A1001A70O",
        license_note=ENTSOE_LICENSE,
    ),
    PriceZone(
        "IT-Centre-South",
        "Italy Centre South",
        ("IT",),
        entsoe_eic="10Y1001A1001A71M",
        license_note=ENTSOE_LICENSE,
    ),
    PriceZone(
        "IT-North",
        "Italy North",
        ("IT",),
        entsoe_eic="10Y1001A1001A73I",
        license_note=ENTSOE_LICENSE,
    ),
    PriceZone(
        "IT-Sardinia",
        "Italy Sardinia",
        ("IT",),
        entsoe_eic="10Y1001A1001A74G",
        license_note=ENTSOE_LICENSE,
    ),
    PriceZone(
        "IT-Sicily",
        "Italy Sicily",
        ("IT",),
        entsoe_eic="10Y1001A1001A75E",
        license_note=ENTSOE_LICENSE,
    ),
    PriceZone(
        "IT-South",
        "Italy South",
        ("IT",),
        entsoe_eic="10Y1001A1001A788",
        license_note=ENTSOE_LICENSE,
    ),
    PriceZone("LV", "Latvia", ("LV",), entsoe_eic="10YLV-1001A00074", license_note=ENTSOE_LICENSE),
    PriceZone(
        "LT", "Lithuania", ("LT",), entsoe_eic="10YLT-1001A0008Q", license_note=ENTSOE_LICENSE
    ),
    PriceZone("MT", "Malta", ("MT",), entsoe_eic="10Y1001A1001A93C", license_note=ENTSOE_LICENSE),
    PriceZone(
        "NL", "Netherlands", ("NL",), entsoe_eic="10YNL----------L", license_note=ENTSOE_LICENSE
    ),
    PriceZone("PL", "Poland", ("PL",), entsoe_eic="10YPL-AREA-----S", license_note=ENTSOE_LICENSE),
    PriceZone(
        "PT", "Portugal", ("PT",), entsoe_eic="10YPT-REN------W", license_note=ENTSOE_LICENSE
    ),
    PriceZone("RO", "Romania", ("RO",), entsoe_eic="10YRO-TEL------P", license_note=ENTSOE_LICENSE),
    PriceZone(
        "SK", "Slovakia", ("SK",), entsoe_eic="10YSK-SEPS-----K", license_note=ENTSOE_LICENSE
    ),
    PriceZone(
        "SI", "Slovenia", ("SI",), entsoe_eic="10YSI-ELES-----O", license_note=ENTSOE_LICENSE
    ),
    PriceZone("ES", "Spain", ("ES",), entsoe_eic="10YES-REE------0", license_note=ENTSOE_LICENSE),
    PriceZone(
        "SE1", "Sweden 1", ("SE",), entsoe_eic="10Y1001A1001A44P", license_note=ENTSOE_LICENSE
    ),
    PriceZone(
        "SE2", "Sweden 2", ("SE",), entsoe_eic="10Y1001A1001A45N", license_note=ENTSOE_LICENSE
    ),
    PriceZone(
        "SE3", "Sweden 3", ("SE",), entsoe_eic="10Y1001A1001A46L", license_note=ENTSOE_LICENSE
    ),
    PriceZone(
        "SE4", "Sweden 4", ("SE",), entsoe_eic="10Y1001A1001A47J", license_note=ENTSOE_LICENSE
    ),
    PriceZone(
        "GB", "Great Britain", ("UK",), entsoe_eic="10YGB----------A", license_note=ENTSOE_LICENSE
    ),
)


def fetch_energy_charts_prices(
    start_year: int,
    end_year: int,
    request_delay_seconds: float = 6.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[pd.DataFrame] = []
    statuses: list[dict[str, Any]] = []
    config = EnergyChartsClientConfig(
        timeout_seconds=60.0,
        max_retries=8,
        backoff_seconds=max(5.0, request_delay_seconds),
        min_request_interval_seconds=request_delay_seconds,
    )
    with EnergyChartsClient(config) as client:
        for zone in ENERGY_CHARTS_ZONES:
            for year in range(start_year, end_year + 1):
                try:
                    print(f"Fetching Energy-Charts {zone.code} {year}")
                    payload = client.get(
                        "/price",
                        bzn=zone.energy_charts_bzn,
                        start=f"{year}-01-01",
                        end=f"{year}-12-31",
                    )
                    rows.append(_energy_charts_payload_to_frame(payload, zone))
                    statuses.append(_status_row(zone, year, "ok", ""))
                except RuntimeError as exc:
                    statuses.append(_status_row(zone, year, "failed", str(exc)))
                    print(f"Skipping Energy-Charts {zone.code} {year}: {exc}")
    return _concat(rows), pd.DataFrame(statuses)


def fetch_entsoe_prices(
    start_year: int,
    end_year: int,
    token: str,
    min_request_interval_seconds: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[pd.DataFrame] = []
    statuses: list[dict[str, Any]] = []
    last_request_at = 0.0
    with httpx.Client(timeout=60.0, headers={"User-Agent": "bess-data-pipeline/0.1"}) as client:
        for zone in ENTSOE_ZONES:
            for year in range(start_year, end_year + 1):
                try:
                    elapsed = time.monotonic() - last_request_at
                    if elapsed < min_request_interval_seconds:
                        time.sleep(min_request_interval_seconds - elapsed)
                    print(f"Fetching ENTSO-E {zone.code} {year}")
                    response = client.get(
                        ENTSOE_API_URL,
                        params=_entsoe_price_params(token, zone, year),
                    )
                    last_request_at = time.monotonic()
                    response.raise_for_status()
                    frame = parse_entsoe_price_xml(response.text, zone)
                    if frame.empty:
                        statuses.append(
                            _status_row(zone, year, "empty", "No price points returned")
                        )
                    else:
                        rows.append(frame)
                        statuses.append(_status_row(zone, year, "ok", ""))
                except (httpx.HTTPError, ValueError) as exc:
                    statuses.append(_status_row(zone, year, "failed", str(exc)))
                    print(f"Skipping ENTSO-E {zone.code} {year}: {exc}")
    return _concat(rows), pd.DataFrame(statuses)


def build_report(
    prices: pd.DataFrame,
    threshold: float,
    start_year: int,
    end_year: int,
    inclusive: bool = False,
) -> dict[str, pd.DataFrame]:
    countries = country_price_frame(prices)
    return {
        "country_hours": annual_hours_below_threshold(
            countries, threshold, start_year, end_year, inclusive, "country_name"
        ),
        "country_cumulative": annual_hours_below_threshold(
            countries, threshold, start_year, end_year, inclusive, "country_name"
        ).cumsum(),
        "zone_hours": annual_hours_below_threshold(
            prices, threshold, start_year, end_year, inclusive, "zone_code"
        ),
    }


def country_price_frame(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame(
            columns=["timestamp_utc", "country_code", "country_name", "price_eur_per_mwh"]
        )

    exploded = prices.explode("country_codes").rename(columns={"country_codes": "country_code"})
    country_prices = (
        exploded.groupby(["timestamp_utc", "country_code"], as_index=False)["price_eur_per_mwh"]
        .mean()
        .dropna(subset=["price_eur_per_mwh"])
    )
    country_prices["country_name"] = country_prices["country_code"].map(
        lambda code: COUNTRIES_BY_CODE[code].name
    )
    return country_prices


def annual_hours_below_threshold(
    frame: pd.DataFrame,
    threshold: float,
    start_year: int,
    end_year: int,
    inclusive: bool,
    column: str,
) -> pd.DataFrame:
    years = list(range(start_year, end_year + 1))
    if frame.empty:
        return pd.DataFrame(index=years)

    with_intervals = _with_interval_hours(frame, column)
    with_intervals["year"] = with_intervals["timestamp_utc"].dt.tz_convert(REPORT_TIMEZONE).dt.year
    if inclusive:
        selected = with_intervals["price_eur_per_mwh"] <= threshold
    else:
        selected = with_intervals["price_eur_per_mwh"] < threshold
    with_intervals["hours_below_threshold"] = with_intervals["interval_hours"].where(selected, 0.0)
    result = with_intervals.groupby(["year", column])["hours_below_threshold"].sum().unstack(column)
    result = result.reindex(years)
    if column == "country_name":
        result = result.reindex(columns=[country.name for country in EU_COUNTRIES_PLUS_UK])
    return result.round(3)


def write_report_workbook(
    path: Path,
    report: dict[str, pd.DataFrame],
    prices: pd.DataFrame,
    statuses: pd.DataFrame,
    source: str,
    threshold: float,
    inclusive: bool,
    start_year: int,
    end_year: int,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    coverage = coverage_frame(prices, statuses, source)
    run_info = pd.DataFrame(
        [
            ("source", source),
            ("threshold_eur_per_mwh", threshold),
            ("comparison", "<= threshold" if inclusive else "< threshold"),
            ("start_year", start_year),
            ("end_year", end_year),
            ("country_method", "simple average of available bidding-zone prices per timestamp"),
            ("generated_at_utc", datetime.now(UTC).isoformat()),
        ],
        columns=["field", "value"],
    )

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        report["country_hours"].to_excel(writer, sheet_name="country_hours")
        report["country_cumulative"].to_excel(writer, sheet_name="country_cumulative")
        report["zone_hours"].to_excel(writer, sheet_name="zone_hours")
        coverage.to_excel(writer, sheet_name="coverage", index=False)
        statuses.to_excel(writer, sheet_name="fetch_status", index=False)
        run_info.to_excel(writer, sheet_name="run_info", index=False)
    return path


def coverage_frame(prices: pd.DataFrame, statuses: pd.DataFrame, source: str) -> pd.DataFrame:
    zones = ENTSOE_ZONES if source == "entsoe" else ENERGY_CHARTS_ZONES
    fetched_zone_codes = set(prices["zone_code"].unique()) if not prices.empty else set()
    rows = []
    for country in EU_COUNTRIES_PLUS_UK:
        country_zones = [zone for zone in zones if country.code in zone.country_codes]
        fetched_zones = [zone.code for zone in country_zones if zone.code in fetched_zone_codes]
        rows.append(
            {
                "country_code": country.code,
                "country": country.name,
                "configured_zones": ", ".join(zone.code for zone in country_zones),
                "fetched_zones": ", ".join(fetched_zones),
                "coverage_status": "ok" if fetched_zones else "no_data",
                "source": source,
                "notes": _coverage_note(country, country_zones, statuses),
                "license_notes": " | ".join(sorted({zone.license_note for zone in country_zones})),
            }
        )
    return pd.DataFrame(rows)


def parse_entsoe_price_xml(text: str, zone: PriceZone) -> pd.DataFrame:
    root = ET.fromstring(text)
    reason = _find_first_text(root, "text")
    time_series = [element for element in root.iter() if _local_name(element.tag) == "TimeSeries"]
    if not time_series and reason:
        raise ValueError(reason)

    rows: list[dict[str, Any]] = []
    for series in time_series:
        currency = _find_first_text(series, "currency_Unit.name")
        unit = _find_first_text(series, "price_Measure_Unit.name")
        for period in _children(series, "Period"):
            start_text = _find_nested_text(period, "timeInterval", "start")
            resolution_text = _find_first_text(period, "resolution")
            if not start_text or not resolution_text:
                continue
            start = _parse_entsoe_datetime(start_text)
            resolution = _resolution_to_timedelta(resolution_text)
            for point in _children(period, "Point"):
                position_text = _find_first_text(point, "position")
                price_text = _find_first_text(point, "price.amount")
                if not position_text or price_text is None:
                    continue
                timestamp = start + (int(position_text) - 1) * resolution
                rows.append(
                    {
                        "timestamp_utc": timestamp,
                        "price_eur_per_mwh": float(price_text),
                        "zone_code": zone.code,
                        "zone_label": zone.label,
                        "country_codes": zone.country_codes,
                        "unit": f"{currency}/{unit}".strip("/"),
                        "license_info": zone.license_note,
                    }
                )
    return pd.DataFrame(rows)


def _energy_charts_payload_to_frame(payload: dict[str, Any], zone: PriceZone) -> pd.DataFrame:
    timestamps = pd.to_datetime(payload.get("unix_seconds") or [], unit="s", utc=True)
    values = payload.get("price") or []
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps[: len(values)],
            "price_eur_per_mwh": values,
            "zone_code": zone.code,
            "zone_label": zone.label,
            "country_codes": [zone.country_codes] * len(values),
            "unit": payload.get("unit"),
            "license_info": payload.get("license_info") or zone.license_note,
        }
    )


def _entsoe_price_params(token: str, zone: PriceZone, year: int) -> dict[str, str]:
    if not zone.entsoe_eic:
        raise ValueError(f"{zone.code} has no ENTSO-E EIC code")
    return {
        "securityToken": token,
        "documentType": "A44",
        "in_Domain": zone.entsoe_eic,
        "out_Domain": zone.entsoe_eic,
        "periodStart": f"{year}01010000",
        "periodEnd": f"{year + 1}01010000",
    }


def _with_interval_hours(frame: pd.DataFrame, group_column: str) -> pd.DataFrame:
    result = frame.dropna(subset=["timestamp_utc", "price_eur_per_mwh", group_column]).copy()
    result["timestamp_utc"] = pd.to_datetime(result["timestamp_utc"], utc=True)
    pieces = []
    for _, group in result.sort_values([group_column, "timestamp_utc"]).groupby(group_column):
        group = group.copy()
        deltas = group["timestamp_utc"].shift(-1) - group["timestamp_utc"]
        positive_hours = deltas.dt.total_seconds().div(3600)
        fallback = positive_hours[positive_hours > 0].median()
        if pd.isna(fallback) or fallback <= 0:
            fallback = 1.0
        group["interval_hours"] = positive_hours.fillna(fallback).clip(lower=0, upper=1)
        pieces.append(group)
    return _concat(pieces)


def _coverage_note(country: ReportCountry, zones: list[PriceZone], statuses: pd.DataFrame) -> str:
    if not zones:
        return (
            "No configured Energy-Charts bidding zone for this country"
            if country.code in {"CY", "IE", "MT", "UK"}
            else ""
        )
    if statuses.empty:
        return ""
    failed = statuses[
        statuses["zone_code"].isin([zone.code for zone in zones])
        & statuses["status"].isin(["failed", "empty"])
    ]
    if failed.empty:
        return ""
    return "; ".join(
        f"{row.zone_code} {row.year}: {row.status}" for row in failed.itertuples(index=False)
    )


def _status_row(zone: PriceZone, year: int, status: str, message: str) -> dict[str, Any]:
    return {
        "zone_code": zone.code,
        "zone_label": zone.label,
        "countries": ", ".join(zone.country_codes),
        "year": year,
        "status": status,
        "message": message,
    }


def _concat(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    valid = [frame for frame in frames if not frame.empty]
    return pd.concat(valid, ignore_index=True) if valid else pd.DataFrame()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if _local_name(child.tag) == name]


def _find_first_text(element: ET.Element, name: str) -> str | None:
    for child in element.iter():
        if _local_name(child.tag) == name:
            return child.text
    return None


def _find_nested_text(element: ET.Element, parent_name: str, child_name: str) -> str | None:
    for parent in element.iter():
        if _local_name(parent.tag) != parent_name:
            continue
        for child in parent:
            if _local_name(child.tag) == child_name:
                return child.text
    return None


def _parse_entsoe_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _resolution_to_timedelta(value: str) -> timedelta:
    if not value.startswith("PT") or not value.endswith("M"):
        raise ValueError(f"Unsupported ENTSO-E resolution: {value}")
    return timedelta(minutes=int(value[2:-1]))


def default_output_path(threshold: float, source: str, start_year: int, end_year: int) -> Path:
    threshold_label = str(threshold).replace(".", "_").replace("-", "minus_")
    return (
        DEFAULT_OUTPUT_DIR
        / f"price_hours_below_{threshold_label}_{source}_{start_year}_{end_year}.xlsx"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an Excel report of annual day-ahead price hours below a threshold."
    )
    parser.add_argument("threshold", type=float, help="Price threshold in EUR/MWh, e.g. 5.")
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument(
        "--source",
        choices=("entsoe", "energy-charts"),
        default="entsoe",
        help="Use ENTSO-E for full EU+UK coverage, or Energy-Charts as a no-token fallback.",
    )
    parser.add_argument(
        "--entsoe-token",
        default=os.getenv("ENTSOE_API_TOKEN"),
        help="ENTSO-E Transparency API token. Defaults to ENTSOE_API_TOKEN.",
    )
    parser.add_argument("--inclusive", action="store_true", help="Count prices <= threshold.")
    parser.add_argument("--output", type=Path, help="Output .xlsx path.")
    parser.add_argument(
        "--request-delay",
        type=float,
        default=6.0,
        help="Seconds between API requests. Increase this if Energy-Charts returns 429.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.end_year < args.start_year:
        raise SystemExit("--end-year must be greater than or equal to --start-year")
    if args.source == "entsoe" and not args.entsoe_token:
        raise SystemExit(
            "ENTSO-E source requires --entsoe-token or ENTSOE_API_TOKEN. "
            "Use --source energy-charts for the no-token fallback."
        )

    ensure_data_dirs()
    if args.source == "entsoe":
        prices, statuses = fetch_entsoe_prices(
            args.start_year,
            args.end_year,
            args.entsoe_token,
            min_request_interval_seconds=args.request_delay,
        )
    else:
        prices, statuses = fetch_energy_charts_prices(
            args.start_year,
            args.end_year,
            request_delay_seconds=args.request_delay,
        )

    report = build_report(prices, args.threshold, args.start_year, args.end_year, args.inclusive)
    output = args.output or default_output_path(
        args.threshold, args.source, args.start_year, args.end_year
    )
    write_report_workbook(
        output,
        report,
        prices,
        statuses,
        args.source,
        args.threshold,
        args.inclusive,
        args.start_year,
        args.end_year,
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
