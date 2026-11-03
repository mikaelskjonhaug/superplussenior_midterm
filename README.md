# Super + Senior

We study how Muni bus access and service quality vary across San Francisco ZIP codes, and how those patterns relate to income and poverty.

## Data

The study covers March 2022 through September 2026. The main table, [`data/cleaned/sf_zip_month_transit.csv`](data/cleaned/sf_zip_month_transit.csv), has 1,485 rows: one for each of 27 ZIP codes in each of 55 months. It combines observed arrivals from 511, historical SFMTA schedules, bus stop locations, ZIP boundaries, and ACS population and income data.

The builder also writes the income, arrival-share, access, service, and model inputs used by the [combined analysis notebook](notebooks/sf_income_and_arrival_analysis.ipynb) to `data/cleaned/notebook/`. The notebook reads these prepared files; it does not clean raw data or run the builder.

## Source data

Saved inputs are in `data/raw/`. The links below identify their providers; some saved extracts have project-specific filenames. See the [raw-data notes](data/raw/README.md) for the input inventory and the [schedule-source notes](data/raw/sfmta_schedule_sources/README.md) for the GTFS archives.

| Saved input under `data/raw/` | Source and use |
| --- | --- |
| `transit_monthly/transit_YYYY-MM.csv` | [511 SF Bay](https://511.org/open-data/transit) monthly ZIP-level arrival snapshots. The large observation archives are not stored here. |
| `sfmta_schedule_sources/regional_gtfs_YYYY-MM.zip` | [511 historical Regional GTFS](https://511.org/open-data/transit) schedules, stored with Git LFS. |
| `sfmta_schedule_sources/sfmta_2022-09.zip` | Archived [SFMTA GTFS](https://www.sfmta.com/reports/gtfs-transit-data) schedule used for August through December 2022 when the Regional archives lacked the needed SFMTA schedule. |
| `SFMTA_GTFS_20260829_20270115v2/` | [SFMTA GTFS](https://www.sfmta.com/reports/gtfs-transit-data) stop and route snapshot used for stop coverage. |
| `San_Francisco_ZIP_Codes_20261007.csv` | [DataSF ZIP boundaries](https://data.sfgov.org/Geographic-Locations-and-Boundaries/San-Francisco-ZIP-Codes/srq6-hmpi) for spatial joins and ZIP area. |
| `acs_2024_sf_zcta.csv`, `ACS_houshold_brackets/` | [ACS five-year estimates](https://www.census.gov/data/developers/data-sets/acs-5year.html) for population, income, and poverty, plus [TIGER/Line block-group boundaries](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html). |
| `acs_income_brackets_by_zip_year.csv` | Saved [ACS income-bracket](https://www.census.gov/programs-surveys/acs/data.html) aggregate. The builder prepares the current cleaned table from block-group Parquet files. |
| `irs_soi/` | [IRS Statistics of Income ZIP data](https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-statistics-zip-code-data-soi) for 2020-2022. |
| `sf_walk_network_edges.parquet` | Saved walking-street network from [OpenStreetMap](https://www.openstreetmap.org/), collected through OSMnx. |

## Processing and data limits

`data_cleaning/clean_511.py` filters Muni bus and trolleybus observations, assigns stops to ZIP codes, and summarizes arrivals and delays by month. It processes the original large archives in chunks. The resulting 55 monthly snapshots are saved in this repository, so a normal rebuild does not download or reprocess those archives.

`data_cleaning/build_dataset.py` joins the snapshots with schedules, stop locations, ZIP areas, and demographics. It fills out all 27 × 55 ZIP-month combinations and writes the prepared notebook tables and map layers. `data/notebook_inputs.json` records their row counts, sizes, and checksums. The scripts print filtering and quality-check counts, including scheduled-time coverage, block-group matches, missing income, and flagged months.

The dataset keeps months with limited 511 coverage but flags them. February 2023 has only 14 observed service days; November 2024 through February 2025 have unusually low arrival volume. The service-frequency analysis uses months that pass both checks. ACS does not report median household income for ZIP 94104, so analyses requiring that measure exclude it.

## Set up

The commands below use Python 3.15.2. From the repository root in PowerShell:

```powershell
git lfs pull
py -3.15 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On macOS or Linux, use `python3.15 -m venv .venv` and `.venv/bin/python -m pip install -r requirements.txt` in place of the last two commands.

**Windows dependency note:** On Python 3.15.2, pip may try to build PyYAML if no compatible wheel is available. That requires Microsoft Visual C++ Build Tools. The failure occurs during dependency installation, before project code runs.

## Run

To check the saved inputs, rebuild the cleaned data, and execute the notebook:

```powershell
.\.venv\Scripts\python.exe main.py
```

The executed notebook is saved as `outputs/sf_income_and_arrival_analysis.executed.ipynb`; ten figures are written to `outputs/`. The command stops if the data build or a notebook cell fails. It uses the saved monthly 511 snapshots and only rebuilds the historical schedule CSV from GTFS archives if that CSV is missing.

To rebuild data without executing the notebook:

```powershell
.\.venv\Scripts\python.exe main.py --skip-notebook
```

To use the included prepared tables without rebuilding data, open `notebooks/sf_income_and_arrival_analysis.ipynb` in JupyterLab, select the `.venv` Python environment, and run all cells:

```powershell
.\.venv\Scripts\python.exe -m jupyterlab notebooks/sf_income_and_arrival_analysis.ipynb
```

The notebook works from the repository root or `notebooks/`. It needs no API keys or downloads. See [`data/NOTEBOOK_INPUTS.md`](data/NOTEBOOK_INPUTS.md) for the prepared input list.

## Rebuild and checks

To run the builder directly after changing source data or processing code:

```powershell
.\.venv\Scripts\python.exe data_cleaning\build_dataset.py
```

To check that the notebook runs with only its cleaned inputs:

```powershell
.\.venv\Scripts\python.exe scripts/check_notebook.py --cleaned-only
```

To test a rebuild and notebook run from source inputs in a temporary workspace:

```powershell
.\.venv\Scripts\python.exe scripts/check_main.py
```

GitHub Actions also runs the notebook and dataset checks. Arrival-share comparisons are descriptive: monthly observations are paired and may be related.
