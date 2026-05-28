# BESS Data Pipeline

A small Python pipeline for collecting BESS-relevant energy data from
[Energy-Charts](https://api.energy-charts.info/) and exploring it in Streamlit.

The first version focuses on the 80/20 useful slice:

- day-ahead prices
- public power generation mix
- public power forecasts
- renewable share forecast and traffic signal
- cross-border electricity trading and physical flows

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .[dev]
```

## Fetch Data

```powershell
.\.venv\Scripts\python.exe -m bess_pipeline.fetch --start 2026-05-01 --end 2026-05-02
```

For a smaller, API-friendly fetch:

```powershell
.\.venv\Scripts\python.exe -m bess_pipeline.fetch --start 2026-05-01 --end 2026-05-01 --country de --bidding-zone DE-LU
```

Add `--spread-hours N` to choose the daily BESS spread window from 1 to 12 hours. The
pipeline stores daily top-minus-bottom price spread metrics and negative-price summaries
in `data/processed/price_daily_analytics.parquet`.

Data is written to:

- `data/raw/` as raw API JSON
- `data/processed/` as tidy Parquet tables

## Streamlit

```powershell
.\.venv\Scripts\streamlit.exe run app/Home.py
```

The dashboard can read cached Parquet files and fetch a selected date range directly.

## Data License

Unless stated otherwise by Energy-Charts, data is licensed under CC BY 4.0 and requires
proper attribution to Energy-Charts.info. Price data includes endpoint-specific licensing
information in the API response and should be reviewed before external or commercial use.
