# Generated cleaned data

This folder can be regenerated from the permanent inputs under `data/raw/`.

`data_cleaning/build_dataset.py` combines the 55 saved transit snapshots,
the historical schedule, ACS values, and access measures to write
`sf_zip_month_transit.csv`.
If the schedule CSV is absent, it first regenerates that CSV from the GTFS
source ZIPs in `data/raw/sfmta_schedule_sources/`.

It also writes all mega-notebook inputs under `notebook/`: 21 CSV tables,
four prepared map layers, and one metadata file. These prepared files are
included so the notebook can also be run directly after cloning.

From the project environment:

- `python main.py`: rebuild the data, then execute every notebook cell.
- `python main.py --skip-notebook`: rebuild the data only.
- `python data_cleaning/build_dataset.py`: call the builder directly.

The saved monthly transit snapshots are in `../raw/transit_monthly/`.
The schedule source archives, IRS 2022 totals, and source street geometry
also live under `../raw/`, so rebuilding never requires collecting those
inputs again.

Partial transit runs write `sf_zip_month_transit_partial.csv`. `main.py`
stops before notebook execution if the build is incomplete.

## Generator for each cleaned dataset

All functions below are in `data_cleaning/build_dataset.py`. Its `main()`
function writes `sf_zip_month_transit.csv` and calls `build_notebook_data()`.
`build_notebook_data()` writes every file under `notebook/` after calling the
listed function. `main.py` orchestrates the rebuild and notebook execution.

| Cleaned file | Function that prepares its contents |
| --- | --- |
| `sf_zip_month_schedule_sfmta_history.csv` | `rebuild_sfmta_schedule()` via `build_schedule()` and `process_schedule_archive()` |
| `sf_zip_month_transit.csv` | `load_checkpoints()` and `build_dataset()` |
| `sf_zip_month_transit_partial.csv` (only for an incomplete source period) | `load_checkpoints()` and `build_dataset()` |
| `notebook/sf_irs_zip_income_2020_2022.csv` | `build_income_tables()` |
| `notebook/sf_acs_income_brackets_by_zip_year.csv` | `build_income_tables()` |
| `notebook/sf_zip_year_socioeconomic_table.csv` | `build_income_tables()` |
| `notebook/sf_zip_socioeconomic_table.csv` | `build_income_tables()` |
| `notebook/income_box_shares.csv` | `build_income_plot_data()` |
| `notebook/income_bracket_outliers.csv` | `build_income_plot_data()` |
| `notebook/income_map_legend.csv` | `build_income_plot_data()` |
| `notebook/income_map_bounds.csv` | `build_income_plot_data()` |
| `notebook/income_availability.csv` | `build_income_plot_data()` |
| `notebook/income_zip_map.parquet` | `build_income_plot_data()` |
| `notebook/sf_street_edges.parquet` | `build_income_plot_data()` |
| `notebook/sf_transit_stops.parquet` | `build_income_plot_data()` |
| `notebook/per_zip_monthly_shares.csv` | `build_arrival_tables()` |
| `notebook/per_zip_kl_ks_results.csv` | `build_arrival_tables()` |
| `notebook/monthly_share_cdfs.csv` | `build_arrival_tables()` via `monthly_share_cdfs()` |
| `notebook/arrival_plot_summary.csv` | `build_arrival_tables()` |
| `notebook/arrival_share_gaps.csv` | `build_arrival_tables()` |
| `notebook/zip_service_summary.csv` | `build_service_tables()` |
| `notebook/monthly_service_summary.csv` | `build_service_tables()` |
| `notebook/service_correlations.csv` | `build_service_tables()` |
| `notebook/service_model_coefficients.csv` | `build_service_tables()` |
| `notebook/income_service_charts.csv` | `build_service_tables()` |
| `notebook/service_chart_labels.csv` | `build_service_tables()` |
| `notebook/service_summary_statistics.csv` | `build_service_tables()` |
| `notebook/service_zip_map.parquet` | `build_service_tables()` |
| `notebook/analysis_metadata.json` | `build_arrival_tables()` and `build_service_tables()` |
