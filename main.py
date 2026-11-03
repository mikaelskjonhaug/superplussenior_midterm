"""Build the cleaned data from saved source inputs, then run the mega notebook."""

import argparse
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

from data_cleaning import build_dataset


ROOT = Path(__file__).resolve().parent
NOTEBOOK = ROOT / 'notebooks/sf_income_and_arrival_analysis.ipynb'


def check_source_inputs():
    required = [
        build_dataset.ZIP_FILE,
        build_dataset.ACS_FILE,
        build_dataset.IRS_2020_FILE,
        build_dataset.IRS_2021_FILE,
        build_dataset.IRS_2022_FILE,
        build_dataset.BLOCK_GROUP_BOUNDARY_FILE,
        build_dataset.STREET_NETWORK_EDGE_FILE,
    ]
    for name in ['routes.txt', 'trips.txt', 'stop_times.txt', 'stops.txt']:
        required.append(build_dataset.GTFS_DIR / name)
    months = build_dataset.month_range(build_dataset.START_MONTH, build_dataset.END_MONTH)
    for month in months:
        required.append(build_dataset.MONTHLY_DIR / f'transit_{month}.csv')
    if not build_dataset.SCHEDULE_FILE.is_file():
        archive_names = {
            'sfmta_2022-09.zip' if month in build_dataset.FALLBACK_MONTHS
            else f'regional_gtfs_{month}.zip'
            for month in months
        }
        required.extend(
            build_dataset.SCHEDULE_SOURCE_DIR / name for name in sorted(archive_names)
        )
    bracket_files = sorted(build_dataset.ACS_BRACKET_DIR.glob('*.parquet'))
    if not bracket_files:
        raise FileNotFoundError(f'No ACS Parquet inputs in {build_dataset.ACS_BRACKET_DIR}')
    required.extend(bracket_files)
    missing = []
    for path in required:
        if not path.is_file():
            missing.append(str(path))
    if missing:
        raise FileNotFoundError('Missing saved source inputs:\n' + '\n'.join(missing))
    print(f'Found {len(required)} saved source inputs, including {len(months)} monthly snapshots.')


def run_notebook():
    output = ROOT / 'outputs/sf_income_and_arrival_analysis.executed.ipynb'
    output.parent.mkdir(parents=True, exist_ok=True)
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    client = NotebookClient(
        notebook,
        timeout=240,
        kernel_name='python3',
        allow_errors=False,
        resources={'metadata': {'path': str(ROOT)}},
    )
    # Use the same Python environment that launched main.py.
    client.create_kernel_manager()
    client.km.kernel_spec.argv = [
        sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}'
    ]
    try:
        client.execute()
    finally:
        nbformat.write(notebook, output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--skip-notebook', action='store_true',
        help='Build the cleaned data without executing the notebook.',
    )
    args = parser.parse_args(argv)

    print('Python:', sys.executable, flush=True)
    print('1/3: Check the saved source inputs.', flush=True)
    check_source_inputs()
    print('2/3: Build the cleaned data and prepared notebook tables.', flush=True)
    result = build_dataset.main()
    if result is None:
        raise RuntimeError('The dataset is incomplete. Notebook execution was stopped.')
    if args.skip_notebook:
        print('Cleaned data is ready. Notebook execution skipped.')
        return
    print('3/3: Execute every cell in the mega notebook.', flush=True)
    output = run_notebook()
    print('Finished. Executed notebook:', output)
    print('Figures are saved under:', ROOT / 'outputs')


if __name__ == '__main__':
    main()
