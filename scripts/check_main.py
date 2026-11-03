"""Test main.py in a fresh workspace using saved raw sources."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from geopandas.testing import assert_geodataframe_equal


ROOT = Path(__file__).resolve().parents[1]


def copy_input(source, destination):
    try:
        os.link(source, destination)
        return destination
    except OSError:
        return shutil.copy2(source, destination)


def file_content(path):
    content = path.read_bytes()
    if path.suffix in {'.csv', '.txt', '.json'}:
        content = content.replace(b'\r\n', b'\n')
    return content


def check_generated_manifest(workspace, expected_manifest):
    manifest = json.loads((workspace / 'data/notebook_inputs.json').read_text())
    expected_paths = {item['path'] for item in expected_manifest['files']}
    actual_paths = {item['path'] for item in manifest['files']}
    assert actual_paths == expected_paths
    builder = workspace / manifest['builder']
    assert hashlib.sha256(file_content(builder)).hexdigest() == manifest['builder_sha256']
    for item in manifest['files']:
        content = file_content(workspace / item['path'])
        assert len(content) == item['bytes']
        assert hashlib.sha256(content).hexdigest() == item['sha256']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--reuse-saved-schedule', action='store_true',
        help='Use the committed cleaned schedule when GTFS LFS files are unavailable.',
    )
    args = parser.parse_args(argv)
    manifest = json.loads((ROOT / 'data/notebook_inputs.json').read_text())
    report_dir = ROOT / 'outputs/main-smoke'
    monthly = ROOT / 'data/raw/transit_monthly'
    before = {}
    for path in monthly.glob('transit_*.csv'):
        before[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if len(before) != 55:
        raise ValueError(f'Expected 55 saved monthly inputs, found {len(before)}')

    with tempfile.TemporaryDirectory(prefix='cp101-main-', dir=ROOT) as folder:
        workspace = Path(folder)
        (workspace / 'data_cleaning').mkdir()
        (workspace / 'notebooks').mkdir()
        for name in ['main.py', 'data_cleaning/build_dataset.py']:
            shutil.copy2(ROOT / name, workspace / name)
        shutil.copy2(
            ROOT / 'notebooks/sf_income_and_arrival_analysis.ipynb',
            workspace / 'notebooks/sf_income_and_arrival_analysis.ipynb',
        )
        shutil.copytree(ROOT / 'data/raw', workspace / 'data/raw', copy_function=copy_input)
        if args.reuse_saved_schedule:
            target = workspace / 'data/cleaned/sf_zip_month_schedule_sfmta_history.csv'
            target.parent.mkdir(parents=True)
            copy_input(ROOT / 'data/cleaned' / target.name, target)
        else:
            assert not (workspace / 'data/cleaned').exists()
        assert not (workspace / 'outputs').exists()
        print('Starting main.py with raw sources and no generated notebook data.', flush=True)

        environment = os.environ.copy()
        (workspace / 'runtime').mkdir()
        environment['IPYTHONDIR'] = str(workspace / 'runtime/ipython')
        environment['JUPYTER_RUNTIME_DIR'] = str(workspace / 'runtime/jupyter')
        subprocess.run(
            [sys.executable, str(workspace / 'main.py')],
            cwd=workspace / 'notebooks',
            env=environment,
            check=True,
        )
        schedule_name = 'sf_zip_month_schedule_sfmta_history.csv'
        rebuilt_schedule = workspace / 'data/cleaned' / schedule_name
        expected_schedule = ROOT / 'data/cleaned' / schedule_name
        assert file_content(rebuilt_schedule) == file_content(expected_schedule)
        check_generated_manifest(workspace, manifest)

        for item in manifest['files']:
            expected = ROOT / item['path']
            actual = workspace / item['path']
            if actual.suffix == '.csv':
                pd.testing.assert_frame_equal(
                    pd.read_csv(actual), pd.read_csv(expected),
                    check_dtype=False, rtol=1e-9, atol=1e-10,
                )
            elif actual.suffix == '.parquet':
                assert_geodataframe_equal(
                    gpd.read_parquet(actual), gpd.read_parquet(expected),
                    check_dtype=False, check_less_precise=True,
                )
            elif actual.suffix == '.json':
                assert json.loads(actual.read_text()) == json.loads(expected.read_text())

        executed_path = workspace / 'outputs/sf_income_and_arrival_analysis.executed.ipynb'
        notebook = json.loads(executed_path.read_text(encoding='utf-8'))
        cells = [cell for cell in notebook['cells'] if cell['cell_type'] == 'code']
        assert all(cell['execution_count'] is not None for cell in cells)
        for cell in cells:
            assert not any(output['output_type'] == 'error' for output in cell['outputs'])
        figures = list((workspace / 'outputs').rglob('*.png'))
        assert len(figures) == 10, f'Expected ten figures, found {len(figures)}'
        report_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(workspace / 'outputs', report_dir, dirs_exist_ok=True)

    for name, checksum in before.items():
        assert hashlib.sha256((monthly / name).read_bytes()).hexdigest() == checksum
    if args.reuse_saved_schedule:
        print('PASS: rebuilt all 26 prepared files from the saved schedule; executed all 15 code cells; created ten figures.')
    else:
        print('PASS: rebuilt the schedule and all 26 prepared files from raw sources; executed all 15 code cells; created ten figures.')
    print('PASS: all 55 saved monthly source files are unchanged.')
    print('Executed notebook and figures:', report_dir)


if __name__ == '__main__':
    main()
