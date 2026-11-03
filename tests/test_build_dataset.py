import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'data_cleaning'))
import build_dataset as dataset
import clean_511


class DatasetTests(unittest.TestCase):
    def test_study_period(self):
        months = dataset.month_range(dataset.START_MONTH, dataset.END_MONTH)
        self.assertEqual(55, len(months))
        self.assertEqual('2022-03', months[0])
        self.assertEqual('2026-09', months[-1])

    def test_time_formats(self):
        values = pd.Series(['01:02:03', '25:00:00', '83667', None, 'bad'])
        result = clean_511.time_to_seconds(values)
        self.assertEqual(3723, result.iloc[0])
        self.assertEqual(90000, result.iloc[1])
        self.assertEqual(83667, result.iloc[2])
        self.assertTrue(pd.isna(result.iloc[3]))
        self.assertTrue(pd.isna(result.iloc[4]))

    def test_monthly_archive_cleaning(self):
        routes = 'route_id,agency_id,route_type\nR1,SF,3\n'
        stops = 'stop_id,stop_lon,stop_lat\nS1,-122.42,37.77\n'
        observations = (
            'trip_id,route_id,stop_id,trip_start_date,schedule_relationship,'
            'scheduled_arrival_time,observed_arrival_time\n'
            'T1,R1,S1,20220301,,3600,3660\n'
            'T2,R1,S1,20220301,,3600,4200\n'
            'T3,R1,S1,20220301,CANCELED,3600,3600\n'
        )
        zip_areas = gpd.GeoDataFrame(
            {'zip_code': ['94102']},
            geometry=[box(-122.43, 37.76, -122.41, 37.78)],
            crs='EPSG:4326',
        ).to_crs('EPSG:7131')
        with tempfile.TemporaryDirectory() as folder:
            archive_path = Path(folder) / 'month.zip'
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.writestr('routes.txt', routes)
                archive.writestr('stops.txt', stops)
                archive.writestr('stop_observations.txt', observations)
            result = clean_511.process_month(archive_path, '2022-03', zip_areas).iloc[0]

        self.assertEqual(2, result['observed_arrivals'])
        self.assertEqual(1, result['observed_stop_count'])
        self.assertEqual(1, result['observed_service_days'])
        self.assertEqual(50.0, result['on_time_pct'])
        self.assertEqual(5.5, result['mean_delay_minutes'])

    def test_physical_and_observed_stops_are_separate(self):
        transit = pd.DataFrame(
            {
                'year_month': ['2022-03'],
                'zip_code': ['94102'],
                'observed_stop_count': [2],
                'observed_arrivals': [100],
                'observed_service_days': [5],
                'on_time_eligible_arrivals': [50],
                'on_time_arrivals': [40],
                'on_time_pct': [80.0],
                'mean_delay_minutes': [1.0],
            }
        )
        zip_areas = pd.DataFrame({'zip_code': ['94102']})
        schedule = pd.DataFrame(
            {
                'year_month': ['2022-03'],
                'zip_code': ['94102'],
                'area_sqmi': [2.0],
                'bus_stop_count': [10],
                'stops_per_sqmi': [5.0],
                'scheduled_arrivals': [120],
                'scheduled_arrivals_per_stop': [12.0],
            }
        )
        walk_coverage = pd.DataFrame(
            {
                'zip_code': ['94102'],
                'quarter_mile_stop_coverage_pct_2026': [75.0],
            }
        )
        acs = pd.DataFrame(
            {
                'zip_code': ['94102'],
                'acs_year': [2024],
                'acs_available': [True],
                'population': [1000],
                'median_household_income': [80000],
                'poverty_universe': [950],
                'below_poverty': [95],
                'poverty_rate': [10.0],
            }
        )
        result = dataset.build_dataset(
            transit, schedule, zip_areas, walk_coverage, acs
        ).iloc[0]
        self.assertEqual(10, result['bus_stop_count'])
        self.assertEqual(2, result['observed_stop_count'])
        self.assertEqual(5.0, result['stops_per_sqmi'])
        self.assertEqual(10.0, result['stops_per_1000_residents'])
        self.assertEqual(-20, result['observed_arrival_gap'])
        self.assertEqual(75.0, result['quarter_mile_stop_coverage_pct_2026'])

    def test_schedule_archive_building(self):
        routes = 'route_id,agency_id,route_type\nR1,SF,3\n'
        trips = 'route_id,service_id,trip_id\nR1,WK,T1\n'
        calendar = (
            'service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,'
            'start_date,end_date\nWK,0,1,1,0,0,0,0,20220301,20220302\n'
        )
        calendar_dates = 'service_id,date,exception_type\nWK,20220303,1\n'
        stop_times = 'trip_id,stop_id\nT1,S1\n'
        stops = 'stop_id,stop_lon,stop_lat\nS1,-122.42,37.77\n'
        zip_areas = gpd.GeoDataFrame(
            {'zip_code': ['94102']},
            geometry=[box(-122.43, 37.76, -122.41, 37.78)],
            crs='EPSG:4326',
        ).to_crs('EPSG:7131')

        with tempfile.TemporaryDirectory() as folder:
            archive_path = Path(folder) / 'schedule.zip'
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.writestr('routes.txt', routes)
                archive.writestr('trips.txt', trips)
                archive.writestr('calendar.txt', calendar)
                archive.writestr('calendar_dates.txt', calendar_dates)
                archive.writestr('stop_times.txt', stop_times)
                archive.writestr('stops.txt', stops)
            result = dataset.process_schedule_archive(
                archive_path, zip_areas, {'2022-03'}
            ).iloc[0]

        self.assertEqual('94102', result['zip_code'])
        self.assertEqual(1, result['bus_stop_count'])
        self.assertEqual(3, result['scheduled_arrivals'])


if __name__ == '__main__':
    unittest.main()
