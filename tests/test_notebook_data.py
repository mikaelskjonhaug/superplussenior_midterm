import ast
import json
import unittest
from pathlib import Path

import pandas as pd

from data_cleaning import build_dataset as dataset


ROOT = Path(__file__).resolve().parents[1]
CLEANED = ROOT / 'data/cleaned/notebook'


class NotebookDataTests(unittest.TestCase):
    def test_only_mega_notebook_remains(self):
        notebooks = list(ROOT.glob('*.ipynb')) + list((ROOT / 'notebooks').glob('*.ipynb'))
        self.assertEqual(
            [ROOT / 'notebooks/sf_income_and_arrival_analysis.ipynb'], notebooks
        )

    def test_notebook_does_not_process_data(self):
        notebook = json.loads(
            (ROOT / 'notebooks/sf_income_and_arrival_analysis.ipynb').read_text(encoding='utf-8')
        )
        processing_methods = {
            'merge', 'groupby', 'to_crs', 'dissolve', 'rank', 'read_excel',
            'to_csv', 'to_parquet', 'fit', 'corr', 'transform',
            'dropna', 'drop_duplicates', 'sort_values',
        }
        for cell in notebook['cells']:
            if cell['cell_type'] != 'code':
                continue
            source = ''.join(cell['source'])
            self.assertNotIn('data/raw', source)
            self.assertNotIn('data_cleaning', source)
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, processing_methods)
                    if node.func.attr in {'read_csv', 'read_parquet'}:
                        path = node.args[0]
                        self.assertIsInstance(path, ast.BinOp)
                        self.assertEqual('DATA_DIR', path.left.id)

    def test_cdf_counts_months_with_ties(self):
        months = pd.DataFrame({
            'observed_share': [0.1, 0.2, 0.2],
            'scheduled_share': [0.1, 0.1, 0.3],
        })
        result = dataset.monthly_share_cdfs(months)
        self.assertEqual([10.0, 20.0, 30.0], result['share_pct'].tolist())
        self.assertEqual([1 / 3, 1.0, 1.0], result['observed'].tolist())
        self.assertEqual([2 / 3, 2 / 3, 1.0], result['scheduled'].tolist())
        self.assertAlmostEqual(1 / 3, result['gap'].max())
        self.assertEqual(10.0, dataset.maximum_cdf_gap(result)['share_pct'])

    def test_cdf_gap_location_ignores_rounding_noise(self):
        cdf = pd.DataFrame({
            'share_pct': [0.99, 1.06, 1.07],
            'gap': [0.2, 0.2 + 1e-16, 0.2],
        })
        self.assertEqual(0.99, dataset.maximum_cdf_gap(cdf)['share_pct'])

    def test_arrival_shares_and_cdf_gaps(self):
        shares = pd.read_csv(CLEANED / 'per_zip_monthly_shares.csv')
        self.assertEqual(1485, len(shares))
        self.assertFalse(shares.duplicated(['year_month', 'zip_code']).any())
        for column in ['observed_share', 'scheduled_share']:
            totals = shares.groupby('year_month')[column].sum()
            self.assertTrue((totals - 1).abs().lt(1e-12).all())
        cdfs = pd.read_csv(CLEANED / 'monthly_share_cdfs.csv')
        results = pd.read_csv(CLEANED / 'per_zip_kl_ks_results.csv').set_index('zip_code')
        for zip_code, cdf in cdfs.groupby('zip_code'):
            self.assertTrue(cdf['observed'].is_monotonic_increasing)
            self.assertTrue(cdf['scheduled'].is_monotonic_increasing)
            self.assertAlmostEqual(results.loc[zip_code, 'ks_statistic'], cdf['gap'].max())

    def test_service_summary_uses_quality_months_and_weighted_rates(self):
        monthly = pd.read_csv(ROOT / 'data/cleaned/sf_zip_month_transit.csv')
        quality = monthly[monthly['data_quality_pass']]
        summary = pd.read_csv(CLEANED / 'zip_service_summary.csv').set_index('zip_code')
        for zip_code, months in quality.groupby('zip_code'):
            row = summary.loc[zip_code]
            stop_days = (months['observed_stop_count'] * months['observed_service_days']).sum()
            self.assertEqual(months['observed_arrivals'].sum(), row['observed_arrivals'])
            self.assertAlmostEqual(
                months['observed_arrivals'].sum() / stop_days,
                row['observed_arrivals_per_stop_per_day'],
            )
            self.assertAlmostEqual(
                100 * months['on_time_arrivals'].sum() / months['on_time_eligible_arrivals'].sum(),
                row['on_time_pct'],
            )


if __name__ == '__main__':
    unittest.main()
