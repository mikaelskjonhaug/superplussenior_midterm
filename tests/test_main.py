import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import nbformat
from nbclient.exceptions import CellExecutionError

import main as pipeline


class MainTests(unittest.TestCase):
    def test_permanent_snapshots_live_outside_generated_folders(self):
        for path in [
            pipeline.build_dataset.MONTHLY_DIR,
            pipeline.build_dataset.IRS_2022_FILE,
            pipeline.build_dataset.STREET_NETWORK_EDGE_FILE,
        ]:
            self.assertTrue(path.is_relative_to(pipeline.build_dataset.RAW_DIR))
        self.assertTrue(
            pipeline.build_dataset.SCHEDULE_FILE.is_relative_to(
                pipeline.build_dataset.CLEANED_DIR
            )
        )

    def test_missing_source_stops_before_building(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / 'missing_zips.csv'
            with patch.object(pipeline.build_dataset, 'ZIP_FILE', missing), patch.object(
                pipeline.build_dataset, 'main'
            ) as build, patch.object(pipeline, 'run_notebook') as run:
                with self.assertRaisesRegex(FileNotFoundError, 'missing_zips.csv'):
                    pipeline.main([])
                build.assert_not_called()
                run.assert_not_called()

    def test_builder_finishes_before_notebook_runs(self):
        with patch.object(pipeline, 'check_source_inputs') as check, patch.object(
            pipeline.build_dataset, 'main', return_value=Path('dataset.csv')
        ) as build, patch.object(pipeline, 'run_notebook', return_value=Path('executed.ipynb')) as run:
            steps = Mock()
            steps.attach_mock(check, 'sources')
            steps.attach_mock(build, 'builder')
            steps.attach_mock(run, 'notebook')
            pipeline.main([])
            self.assertEqual([call.sources(), call.builder(), call.notebook()], steps.mock_calls)

    def test_incomplete_data_stops_notebook_execution(self):
        with patch.object(pipeline, 'check_source_inputs'), patch.object(
            pipeline.build_dataset, 'main', return_value=None
        ), patch.object(pipeline, 'run_notebook') as run:
            with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                pipeline.main([])
            run.assert_not_called()

    def test_skip_notebook_still_builds_data(self):
        with patch.object(pipeline, 'check_source_inputs'), patch.object(
            pipeline.build_dataset, 'main', return_value=Path('dataset.csv')
        ) as build, patch.object(pipeline, 'run_notebook') as run:
            pipeline.main(['--skip-notebook'])
            build.assert_called_once()
            run.assert_not_called()

    def test_notebook_failure_is_saved_and_propagated(self):
        notebook = nbformat.v4.new_notebook(
            cells=[nbformat.v4.new_code_cell("raise ValueError('intentional test failure')")]
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'test.ipynb'
            nbformat.write(notebook, source)
            with patch.object(pipeline, 'ROOT', root), patch.object(pipeline, 'NOTEBOOK', source):
                with self.assertRaises(CellExecutionError):
                    pipeline.run_notebook()
            failed = nbformat.read(
                root / 'outputs/sf_income_and_arrival_analysis.executed.ipynb', as_version=4
            )
            self.assertEqual('error', failed.cells[0].outputs[-1].output_type)


if __name__ == '__main__':
    unittest.main()
