# Mega notebook

`sf_income_and_arrival_analysis.ipynb` is the only analysis notebook. Select
the environment installed from `../requirements.txt` and choose **Run All**.

It reads only the prepared CSV, JSON, and GeoParquet files in
`../data/cleaned/notebook/`. It displays tables and creates ten figures.
It does not import the builder, read raw inputs, or prepare analysis data.

To rebuild the cleaned inputs separately, run
`python data_cleaning/build_dataset.py` from the repository root.

To rebuild the data and then execute this notebook automatically, run
`python main.py` from the project environment. It saves an executed copy under
`outputs/`. `python main.py --skip-notebook` rebuilds only the data.

Income preparation, arrival comparisons, access maps, service charts,
correlations, and regression results from the retired notebooks are combined
here. The notebook works from the repository root or this folder.
