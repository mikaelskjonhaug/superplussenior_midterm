# Permanent source inputs

These files are the starting point for the current workflow. Some are saved
snapshots already collected and aggregated by the earlier pipeline. Keep them
when clearing generated files from `data/cleaned/` or `outputs/`.

## Collected transit snapshots

- `transit_monthly/transit_YYYY-MM.csv`: the 55 saved 511 monthly snapshots,
  March 2022 through September 2026.
- `sfmta_schedule_sources/`: the historical GTFS schedule files used to
  produce `../cleaned/sf_zip_month_schedule_sfmta_history.csv`. The ZIP files
  retain the original GTFS member contents and are tracked with Git LFS. See
  the folder README for provenance.

The local rebuild combines the saved monthly observation snapshots instead
of collecting the historical 511 archives again. When the cleaned schedule
table is absent, `main.py` also regenerates it from the GTFS schedule sources.

## Other saved inputs

- `irs_soi/20zp05ca.xlsx` and `irs_soi/21zp05ca.xlsx`: IRS workbooks.
- `irs_soi/irs_soi_2022_sf_zip_totals.csv`: saved IRS 2022 ZIP totals.
- `ACS_houshold_brackets/`: ACS income extracts and Census block group shapes.
- `acs_2024_sf_zcta.csv`: ACS ZIP estimates.
- `San_Francisco_ZIP_Codes_20261007.csv`: DataSF ZIP boundaries.
- `sf_walk_network_edges.parquet`: saved SF street geometry.
- `SFMTA_GTFS_20260829_20270115v2/`: routes, trips, stop times, stop locations,
  and the SFMTA source license.

The 55 monthly snapshots and IRS totals previously lived in `data/cleaned/`;
the street geometry previously lived in `outputs/`. They were moved here
without changing their contents.

To regenerate the saved schedule from the historical GTFS source ZIPs:

```shell
git lfs pull
python data_cleaning/build_dataset.py --build-schedule
```

The generator lives in `data_cleaning/build_dataset.py`. Its output is the
committed `data/cleaned/sf_zip_month_schedule_sfmta_history.csv`. A normal
cleaned-data rebuild uses that saved CSV when present and regenerates it from
the GTFS source ZIPs when absent.

Run `python main.py` in the project environment to rebuild the cleaned data
and execute the notebook. All source data stays in place.
