# Cleaned inputs for the mega notebook

The notebook reads only `data/cleaned/notebook/`. The 26 included files are
produced by `data_cleaning/build_dataset.py`: 21 CSV tables, four GeoParquet
layers, and one JSON file. No processing script runs inside the notebook.

| Prepared data | Files |
| --- | --- |
| Income tables | IRS by year, ACS income brackets by year, ZIP/year income, current ZIP income, and availability counts |
| Income box plots | Household shares by bracket and annotated ZIP outliers |
| Income map | ZIP groups, street geometry, transit stop points, legend labels, and map bounds |
| Arrival comparisons | Monthly shares, per-ZIP KS/KL results, CDF coordinates, gap highlights, and ordered share differences |
| Access and service | Weighted ZIP summaries, monthly trends, service map, income/service chart data, annotation positions, and summary statistics |
| Statistical results | Pearson correlations, coefficients from four regression models, and metadata including Spearman correlations |

The manifest `data/notebook_inputs.json` records each prepared file's hash
and size. CSV and JSON hashes normalize Git text line endings.

## Rebuild separately

From the repository root, after installing `requirements.txt`:

```shell
python data_cleaning/build_dataset.py
```

The builder first assembles the existing transit checkpoints, then prepares
all notebook files. It reads the committed IRS workbooks, ACS extracts,
Census block group boundaries, DataSF ZIP boundaries, transit tables, and
saved street network. Rebuilding requires those source files; running the
notebook only requires the prepared files.

Permanent inputs live under `data/raw/`, including all 55 monthly checkpoints
in `transit_monthly/`, the historical GTFS schedule sources, IRS 2022 ZIP totals,
and street network. When `data/cleaned/` is empty, the builder regenerates the
SFMTA schedule table from those GTFS sources before creating the notebook inputs.

`python main.py` checks those inputs, calls the builder, and executes the
notebook in that order. `python main.py --skip-notebook` stops after the build.

## Check the boundary

```shell
python scripts/check_notebook.py --cleaned-only --cwd root
python scripts/check_notebook.py --cleaned-only --cwd notebooks
python scripts/check_main.py
```

These commands copy only the prepared inputs into a temporary workspace,
execute every cell in a fresh kernel, and check all ten figures. The temporary
workspace has no raw data or Python builder. Tests also reject joins,
aggregation, feature engineering, model fitting, and data exports in the notebook.

Arrival-share comparisons retain quality-flagged months and use descriptive
KS p-values for paired observations. Service summaries and charts use only
quality-passing months. The two income/service charts exclude ZIP 94104,
whose median household income is unavailable.
