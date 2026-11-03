# Super + Senior

This project studies whether Muni bus access and service quality differ across
San Francisco ZIP codes and whether those differences are associated with
income and poverty.

## Dataset

The study covers March 2022 through September 2026. The dataset has one row per
ZIP code per month: 27 ZIP codes across 55 months, or 1,485 rows.

`data/cleaned/sf_zip_month_transit.csv` combines:

- 511 historical observations for monthly arrivals and reliability
- Historical SFMTA schedules for monthly stops and scheduled arrivals
- The late-2026 SFMTA GTFS feed for quarter-mile stop coverage
- DataSF ZIP boundaries for stop assignment and ZIP area
- ACS 2024 data for population, income, and poverty

## Raw Data Sources

The exact saved inputs are in `data/raw/`. The links below point to the data
providers; saved CSV and Parquet extracts may not be offered there with the
same filenames.

| Saved input under `data/raw/` | Source and role in this project |
| --- | --- |
| `transit_monthly/transit_YYYY-MM.csv` | [511 SF Bay transit data](https://511.org/open-data/transit): 55 monthly ZIP-level observation snapshots, March 2022 through September 2026, prepared from historical Regional feeds with `stop_observations.txt`. These CSVs are already aggregated; the large observation archives are not in this repo. |
| `sfmta_schedule_sources/regional_gtfs_YYYY-MM.zip` | [511 SF Bay historical Regional GTFS](https://511.org/open-data/transit): 50 monthly schedule archives. The ZIPs retain the GTFS members needed by the schedule builder and are stored with Git LFS. |
| `sfmta_schedule_sources/sfmta_2022-09.zip` | An archived [SFMTA GTFS](https://www.sfmta.com/reports/gtfs-transit-data) feed used for August through December 2022 where the Regional archives did not contain the required SFMTA schedule. The [schedule-source notes](data/raw/sfmta_schedule_sources/README.md) give the archived URL and packaging details. |
| `SFMTA_GTFS_20260829_20270115v2/` | [SFMTA GTFS transit data](https://www.sfmta.com/reports/gtfs-transit-data): a saved late-2026 feed with routes, trips, stop times, stops, and its license. It supplies the stop-coverage snapshot. |
| `San_Francisco_ZIP_Codes_20261007.csv` | [DataSF San Francisco ZIP Codes](https://data.sfgov.org/Geographic-Locations-and-Boundaries/San-Francisco-ZIP-Codes/srq6-hmpi): saved ZIP-area boundaries used for spatial assignments and ZIP area. |
| `acs_2024_sf_zcta.csv` | [U.S. Census ACS 5-year data](https://www.census.gov/data/developers/data-sets/acs-5year.html): a saved 2024 ZCTA extract for population, household income, and poverty. |
| `ACS_houshold_brackets/*.parquet` | [U.S. Census ACS 5-year data](https://www.census.gov/programs-surveys/acs/data.html): prepared block-group household-income-bracket extracts. |
| `ACS_houshold_brackets/tl_2024_06_bg.zip` | [U.S. Census TIGER/Line shapefiles](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html): 2024 California block-group boundaries used to assign ACS block groups to ZIP areas. |
| `acs_income_brackets_by_zip_year.csv` | A saved ZIP/year aggregate of [ACS income-bracket data](https://www.census.gov/programs-surveys/acs/data.html). The current builder prepares its cleaned bracket table from the block-group Parquet files instead of reading this CSV. |
| `irs_soi/20zp05ca.xlsx`, `irs_soi/21zp05ca.xlsx` | [IRS Statistics of Income ZIP Code data](https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-statistics-zip-code-data-soi): California workbooks for tax years 2020 and 2021. |
| `irs_soi/irs_soi_2022_sf_zip_totals.csv` | A saved San Francisco ZIP extract from the [IRS 2022 Statistics of Income ZIP Code data](https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-statistics-zip-code-data-soi). |
| `sf_walk_network_edges.parquet` | A saved San Francisco walking-street extract from [OpenStreetMap](https://www.openstreetmap.org/), collected through OSMnx for the access maps. |

The cleaned-data rebuild uses the saved 511 monthly snapshots. It does not
download the original 511 observation archives again. Run `git lfs pull` after
cloning to download the historical schedule ZIP contents before rebuilding the
schedule CSV from raw inputs.

## Cleaning process

For each 511 month, `clean_511.py` keeps Muni bus and trolleybus routes,
assigns stops to ZIP polygons, removes canceled and invalid observations,
converts arrival times to seconds, and calculates arrivals and delays by ZIP.
It reads large observation files in chunks and saves one small monthly
checkpoint CSV.

`build_dataset.py` then combines the 55 checkpoints with the 55-month schedule table,
creates every ZIP-month pair, adds ACS values, and writes the final dataset. It
calculates scheduled stops per square mile, stops per 1,000 residents,
observed-versus-scheduled arrival gaps, and the share of each ZIP within a
quarter mile of a late-2026 bus stop.

The same Python builder also prepares income tables, income groups, map layers,
arrival shares and KS/KL results, weighted service summaries, correlations, and
regression results under `data/cleaned/notebook/`.
It also refreshes `data/notebook_inputs.json`, which records each prepared
file's row count, size, and checksum.

Both cleaning scripts print labeled row counts after filtering, removing
duplicates, joining data, and creating summaries. Each saved cleaned table and
map layer also prints its row count. The 511 cleaner reports stop filtering and
the final monthly ZIP summary, including zero-row results.
The builder also prints the total retained 511 observations, observations with
and without scheduled times, matched block groups, missing income rows, and
quality-check results used in the project report. These values come directly
from the saved monthly checkpoints and final cleaned dataset.

The dataset records a coverage-days flag and a citywide volume flag for each
month. The volume flag fails when arrivals per covered day are below 70% of the
typical month. The overall quality flag passes only when both checks pass.

February 2023 contains only 14 observed service days and therefore fails the
coverage-days rule. November 2024 through February 2025 fail the volume rule.
The rows remain in the dataset so missing feed coverage is visible, but they
should not be used for frequency analysis. ACS does not report median household
income for ZIP 94104.

## Setup

The commands below use Python 3.15.2. Install the listed dependencies once:

From the repository root in PowerShell:

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On macOS or Linux, use `python3.15 -m venv .venv` and
`.venv/bin/python -m pip install -r requirements.txt`.

**Windows dependency note:** With Python 3.15.2, the installation may stop at
PyYAML, which JupyterLab brings in indirectly. If the selected PyYAML release
has no compatible Windows wheel, pip tries to compile it from source and
requires Microsoft Visual C++ Build Tools. This happens during dependency
installation, before any project code runs.

## Run the combined notebook

To rebuild all generated data and run the notebook from one command:

```powershell
.\.venv\Scripts\python.exe main.py
```

`main.py` runs these steps in order:

1. Check the saved source inputs, including the 55 monthly transit snapshots.
2. Run Tila's `data_cleaning/build_dataset.py` to build the transit table and
   all 26 prepared notebook files.
3. Execute the mega notebook in a fresh Jupyter kernel using the same Python
   environment that launched `main.py`.

The executed copy is saved to
`outputs/sf_income_and_arrival_analysis.executed.ipynb`, with ten figure files
under `outputs/`. Notebook errors stop the command and remain visible in the
executed copy.

The already-collected monthly snapshots are permanent inputs under
`data/raw/transit_monthly/`. Historical GTFS schedule sources, IRS 2022 ZIP
totals, and street network are also in `data/raw/`. If the cleaned schedule
table is absent, this command regenerates it from those GTFS sources. It
never restarts the historical 511 collection.

To rebuild the data without executing the notebook:

```powershell
.\.venv\Scripts\python.exe main.py --skip-notebook
```

To work in the notebook interactively:

Open `notebooks/sf_income_and_arrival_analysis.ipynb`, select the `.venv`
Python environment, and click **Run All**. This is the only analysis notebook.
It loads the prepared data and displays income, arrival, access, and service
figures. All cleaning, joins, derived measures, and statistical calculations
are handled by `data_cleaning/build_dataset.py`.

All 26 cleaned input files are included under `data/cleaned/notebook/`. The
notebook never reads raw files or runs the builder. You do not need API keys,
a download step, or a dataset rebuild to run the notebook.
See `data/NOTEBOOK_INPUTS.md` for the input list.

To use JupyterLab from PowerShell:

```powershell
.\.venv\Scripts\python.exe -m jupyterlab notebooks/sf_income_and_arrival_analysis.ipynb
```

The notebook works from the repository root or the `notebooks/` folder.
It creates ten figures under `outputs/`. Prepared CSV tables, map layers, and
statistical results are stored in `data/cleaned/notebook/`. Arrival-share
comparisons remain descriptive because months are paired and may be related.

To verify every input and execute every cell in a fresh kernel:

```powershell
.\.venv\Scripts\python.exe scripts/check_notebook.py --cleaned-only
```

This test runs the notebook in a temporary folder containing only the cleaned
inputs, without the raw files or Python builder. GitHub Actions runs it from
both supported working directories and also runs the dataset tests.

## Rebuild the cleaned data

Run this separately when the source data or processing changes. It rebuilds
the transit table and all 26 cleaned notebook files using local inputs.

```powershell
.\.venv\Scripts\python.exe data_cleaning\build_dataset.py
```

All 55 checkpoint CSVs are stored in the repository, so this command works on a
new device without downloading the large 511 archives.

To test the complete startup order with no generated data present:

```powershell
.\.venv\Scripts\python.exe scripts/check_main.py
```

This creates a temporary workspace with source inputs only, runs `main.py`,
compares the rebuilt data with the included snapshot, checks every notebook
cell and all ten figures, and verifies the 55 source CSVs were not changed.


The former root `data_processing.ipynb` and separate income/service notebooks
have been consolidated into the mega notebook. Their access maps, service
trends, income charts, correlations, and four regression models are retained.
