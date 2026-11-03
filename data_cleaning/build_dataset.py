import argparse
import hashlib
import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import numpy as np
import statsmodels.formula.api as smf
from scipy.stats import ks_2samp, pearsonr


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / 'data' / 'raw'
CLEANED_DIR = ROOT / 'data' / 'cleaned'
MONTHLY_DIR = RAW_DIR / 'transit_monthly'
GTFS_DIR = RAW_DIR / 'SFMTA_GTFS_20260829_20270115v2'
ZIP_FILE = RAW_DIR / 'San_Francisco_ZIP_Codes_20261007.csv'
ACS_FILE = RAW_DIR / 'acs_2024_sf_zcta.csv'
SCHEDULE_FILE = CLEANED_DIR / 'sf_zip_month_schedule_sfmta_history.csv'

START_MONTH = '2022-03'
END_MONTH = '2026-09'
MIN_OBSERVED_DAYS = 20
MIN_VOLUME_PCT = 70
CHUNK_SIZE = 250_000

NOTEBOOK_DIR = CLEANED_DIR / 'notebook'
NOTEBOOK_MANIFEST = ROOT / 'data' / 'notebook_inputs.json'
IRS_2020_FILE = RAW_DIR / 'irs_soi/20zp05ca.xlsx'
IRS_2021_FILE = RAW_DIR / 'irs_soi/21zp05ca.xlsx'
IRS_2022_FILE = RAW_DIR / 'irs_soi/irs_soi_2022_sf_zip_totals.csv'
ACS_BRACKET_DIR = RAW_DIR / 'ACS_houshold_brackets'
BLOCK_GROUP_BOUNDARY_FILE = ACS_BRACKET_DIR / 'tl_2024_06_bg.zip'
ACS_BLOCK_GROUP_YEAR = 2024
STREET_NETWORK_EDGE_FILE = RAW_DIR / 'sf_walk_network_edges.parquet'
GTFS_STOPS_FILE = GTFS_DIR / 'stops.txt'
SCHEDULE_SOURCE_DIR = RAW_DIR / 'sfmta_schedule_sources'
STUDY_START_MONTH = START_MONTH
STUDY_END_MONTH = END_MONTH
BUS_ROUTE_TYPE = 3
SF_AGENCY_IDS = {'SF', 'SFMTA'}
FALLBACK_MONTHS = {'2022-08', '2022-09', '2022-10', '2022-11', '2022-12'}

INCOME_BRACKET_COLUMNS = [
    'HH_INCOME_LT_10K', 'HH_INCOME_10_15K',
    'HH_INCOME_15_20K', 'HH_INCOME_20_25K',
    'HH_INCOME_25_30K', 'HH_INCOME_30_35K',
    'HH_INCOME_35_40K', 'HH_INCOME_40_45K',
    'HH_INCOME_45_50K', 'HH_INCOME_50_60K',
    'HH_INCOME_60_75K', 'HH_INCOME_75_100K',
    'HH_INCOME_100_125K', 'HH_INCOME_125_150K',
    'HH_INCOME_150_200K', 'HH_INCOME_GTE_200K'
]


def month_range(start, end):
    return pd.period_range(start, end, freq='M').astype(str).tolist()


def load_zip_areas():
    data = pd.read_csv(ZIP_FILE, dtype='string')
    zip_column = 'zip_code' if 'zip_code' in data.columns else 'zip'
    zip_codes = data[zip_column].str.replace(r'\.0$', '', regex=True).str.zfill(5)
    areas = gpd.GeoDataFrame(
        {'zip_code': zip_codes},
        geometry=gpd.GeoSeries.from_wkt(data['geometry']),
        crs='EPSG:4326',
    )
    areas = areas.dissolve(by='zip_code', as_index=False).to_crs('EPSG:7131')
    print(f'ZIP boundaries after combining duplicate ZIPs: {len(areas):,} rows')
    areas['area_sqmi'] = areas.geometry.area / (1609.344**2)
    return areas


def get_bus_routes(routes):
    route_type = pd.to_numeric(routes['route_type'], errors='coerce')
    agency = routes['agency_id'].fillna('').str.upper()
    keep = route_type.isin([3, 11]) & agency.isin(['SF', 'SFMTA'])
    bus_routes = set(routes.loc[keep, 'route_id'].dropna().astype(str))
    print(f'Unique Muni bus routes after agency/type filtering: {len(bus_routes):,} rows')
    return bus_routes


def build_walk_coverage(zip_areas):
    routes = pd.read_csv(GTFS_DIR / 'routes.txt', dtype='string')
    trips = pd.read_csv(GTFS_DIR / 'trips.txt', dtype='string')
    bus_routes = get_bus_routes(routes)
    bus_trips = set(trips.loc[trips['route_id'].isin(bus_routes), 'trip_id'])
    print(f'Unique GTFS trips after bus-route filtering: {len(bus_trips):,} rows')

    bus_stops = set()
    chunks = pd.read_csv(
        GTFS_DIR / 'stop_times.txt',
        dtype='string',
        usecols=['trip_id', 'stop_id'],
        chunksize=CHUNK_SIZE,
    )
    for chunk in chunks:
        bus_stops.update(
            chunk.loc[chunk['trip_id'].isin(bus_trips), 'stop_id'].dropna()
        )
    print(f'Unique GTFS stop IDs after bus-trip filtering: {len(bus_stops):,} rows')

    stops = pd.read_csv(
        GTFS_DIR / 'stops.txt',
        dtype='string',
        usecols=['stop_id', 'stop_lon', 'stop_lat'],
    )
    stops = stops[stops['stop_id'].isin(bus_stops)]
    print(f'GTFS stops after bus-stop filtering: {len(stops):,} rows')
    stops['stop_lon'] = pd.to_numeric(stops['stop_lon'], errors='coerce')
    stops['stop_lat'] = pd.to_numeric(stops['stop_lat'], errors='coerce')
    stops = stops.dropna(subset=['stop_lon', 'stop_lat'])
    print(f'GTFS stops after removing invalid coordinates: {len(stops):,} rows')
    points = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(stops['stop_lon'], stops['stop_lat']),
        crs='EPSG:4326',
    ).to_crs(zip_areas.crs)
    covered_area = points.geometry.buffer(0.25 * 1609.344).union_all()
    coverage = zip_areas.geometry.intersection(covered_area).area
    result = zip_areas[['zip_code']].copy()
    result['quarter_mile_stop_coverage_pct_2026'] = (
        100 * coverage / zip_areas.geometry.area
    )
    print(f'Walk coverage after summarizing by ZIP: {len(result):,} rows')
    return result


def load_checkpoints():
    files = sorted(MONTHLY_DIR.glob('transit_*.csv'))
    if not files:
        print('Cleaned monthly checkpoints: 0 rows (no saved files found)')
        return pd.DataFrame()
    frames = [pd.read_csv(path, dtype={'zip_code': 'string'}) for path in files]
    data = pd.concat(frames, ignore_index=True)
    data = data.drop(columns='cache_version', errors='ignore')
    valid_months = month_range(START_MONTH, END_MONTH)
    data = data[data['year_month'].isin(valid_months)]
    print(f'Monthly checkpoints after study-period filtering: {len(data):,} rows')
    data = data.drop_duplicates(['year_month', 'zip_code'])
    print(f'Monthly checkpoints after removing duplicate ZIP-months: {len(data):,} rows')
    observed = int(data['observed_arrivals'].sum())
    eligible = int(data['on_time_eligible_arrivals'].sum())
    print(f'511 observations retained after cleaning: {observed:,} rows')
    print(f'511 observations eligible for on-time calculations: {eligible:,} rows')
    print(f'511 observations without a scheduled time: {observed - eligible:,} rows')
    return data


def build_dataset(transit, schedule, zip_areas, walk_coverage, acs):
    rows = []
    for month in sorted(transit['year_month'].unique()):
        for zip_code in sorted(zip_areas['zip_code']):
            rows.append({'year_month': month, 'zip_code': zip_code})

    data = pd.DataFrame(rows)
    data = data.merge(transit, on=['year_month', 'zip_code'], how='left')
    print(f'ZIP-month grid after joining observed transit: {len(data):,} rows')
    data = data.merge(schedule, on=['year_month', 'zip_code'], how='left')
    print(f'ZIP-month data after joining schedules: {len(data):,} rows')
    data = data.merge(walk_coverage, on='zip_code', how='left')
    print(f'ZIP-month data after joining walk coverage: {len(data):,} rows')
    data = data.merge(acs, on='zip_code', how='left')
    print(f'ZIP-month data after joining ACS values: {len(data):,} rows')

    count_columns = [
        'observed_stop_count',
        'observed_service_days',
        'observed_arrivals',
        'on_time_eligible_arrivals',
        'on_time_arrivals',
    ]
    for column in count_columns:
        data[column] = data[column].fillna(0).astype(int)

    active_stops = data['observed_stop_count'].replace(0, pd.NA)
    service_days = data['observed_service_days'].replace(0, pd.NA)
    scheduled_stops = data['bus_stop_count'].replace(0, pd.NA)
    scheduled_arrivals = data['scheduled_arrivals'].replace(0, pd.NA)
    population = data['population'].replace(0, pd.NA)
    data['observed_to_scheduled_stop_pct'] = (
        100 * data['observed_stop_count'] / scheduled_stops
    )
    data['observed_arrivals_per_stop_per_day'] = (
        data['observed_arrivals'] / active_stops / service_days
    )
    data['stops_per_1000_residents'] = 1000 * data['bus_stop_count'] / population
    data['observed_arrival_gap'] = (
        data['observed_arrivals'] - data['scheduled_arrivals']
    )
    data['observed_arrival_gap_pct'] = (
        100 * data['observed_arrival_gap'] / scheduled_arrivals
    )
    data['observed_arrivals_pct_of_scheduled'] = (
        100 * data['observed_arrivals'] / scheduled_arrivals
    )
    data['coverage_days_quality_pass'] = (
        data['observed_service_days'].ge(MIN_OBSERVED_DAYS)
        & data['observed_stop_count'].gt(0)
        & data['on_time_eligible_arrivals'].gt(0)
    )

    monthly_volume = data.groupby('year_month', as_index=False).agg(
        citywide_observed_arrivals=('observed_arrivals', 'sum'),
        citywide_observed_service_days=('observed_service_days', 'median'),
    )
    monthly_volume['citywide_arrivals_per_service_day'] = (
        monthly_volume['citywide_observed_arrivals']
        / monthly_volume['citywide_observed_service_days']
    )
    complete_months = monthly_volume['citywide_observed_service_days'].ge(
        MIN_OBSERVED_DAYS
    )
    typical_volume = monthly_volume.loc[
        complete_months, 'citywide_arrivals_per_service_day'
    ].median()
    monthly_volume['volume_pct_of_typical'] = (
        100 * monthly_volume['citywide_arrivals_per_service_day'] / typical_volume
    )
    monthly_volume['volume_quality_pass'] = monthly_volume['volume_pct_of_typical'].ge(
        MIN_VOLUME_PCT
    )
    data = data.merge(monthly_volume, on='year_month', how='left')
    data['data_quality_pass'] = (
        data['coverage_days_quality_pass'] & data['volume_quality_pass']
    )
    quality_rows = data['data_quality_pass'].sum()
    service_day_failures = (~data['coverage_days_quality_pass']).sum()
    volume_failures = (~data['volume_quality_pass']).sum()
    missing_income = data['median_household_income'].isna().sum()
    duplicates = data.duplicated(['year_month', 'zip_code']).sum()
    print(f'ZIP-month rows passing quality checks: {quality_rows:,} of {len(data):,} rows')
    print(f'ZIP-month rows failing the service-day check: {service_day_failures:,} rows')
    print(f'ZIP-month rows failing the volume check: {volume_failures:,} rows')
    print(f'ZIP-month rows missing median household income: {missing_income:,} rows')
    print(f'Duplicate ZIP-month rows in final data: {duplicates:,} rows')

    numeric_columns = data.select_dtypes(include='number').columns
    data[numeric_columns] = data[numeric_columns].round(3)
    return data.sort_values(['year_month', 'zip_code']).reset_index(drop=True)


def build_income_tables(zip_geography):
    sf_zips = sorted(zip_geography['zip_code'].unique())
    irs_numeric_columns = [
        'returns', 'individuals', 'agi_thousands',
        'returns_with_wages', 'wages_thousands'
    ]
    irs_columns = ['tax_year', 'zip'] + irs_numeric_columns
    irs_files = [(2020, IRS_2020_FILE), (2021, IRS_2021_FILE)]
    irs_tables = []

    for year, file in irs_files:
        irs = pd.read_excel(file, header=3, usecols=[0, 1, 2, 11, 18, 21, 22])
        irs.columns = ['zip', 'income_group'] + irs_numeric_columns
        irs['zip'] = irs['zip'].astype('string').str.zfill(5)
        irs['income_group'] = irs['income_group'].astype('string').str.strip()

        irs = irs[irs['income_group'].isna() & irs['zip'].isin(sf_zips)].copy()
        print(f'IRS {year} after keeping SF ZIP totals: {len(irs):,} rows')
        irs['tax_year'] = year
        irs_tables.append(irs[irs_columns])

    irs_2022 = pd.read_csv(IRS_2022_FILE, dtype={'zip': 'string'})
    irs_2022['zip'] = irs_2022['zip'].str.zfill(5)
    irs_2022 = irs_2022[irs_2022['zip'].isin(sf_zips)].copy()
    print(f'IRS 2022 after SF ZIP filtering: {len(irs_2022):,} rows')
    irs_2022['tax_year'] = 2022
    irs_tables.append(irs_2022[irs_columns])

    irs_zip_income_by_year = pd.concat(irs_tables, ignore_index=True)
    for column in irs_numeric_columns:
        irs_zip_income_by_year[column] = pd.to_numeric(
            irs_zip_income_by_year[column], errors='coerce'
        )

    irs_zip_income_by_year['agi_per_return_usd'] = (
        irs_zip_income_by_year['agi_thousands'] * 1000
        / irs_zip_income_by_year['returns']
    )
    irs_zip_income_by_year['wages_per_wage_return_usd'] = (
        irs_zip_income_by_year['wages_thousands'] * 1000
        / irs_zip_income_by_year['returns_with_wages']
    )
    irs_zip_income_by_year = irs_zip_income_by_year.sort_values(['tax_year', 'zip'])
    irs_zip_income_by_year = irs_zip_income_by_year.reset_index(drop=True)

    latest_irs_tax_year = irs_zip_income_by_year['tax_year'].max()
    irs_zip_income = irs_zip_income_by_year[
        irs_zip_income_by_year['tax_year'] == latest_irs_tax_year
    ].copy()

    acs_columns = [
        'zip',
        'acs_year',
        'acs_population',
        'acs_median_household_income',
        'acs_poverty_universe',
        'acs_below_poverty',
        'acs_poverty_rate',
    ]

    acs_zip_income = pd.read_csv(ACS_FILE, dtype={'zip_code': 'string'})
    acs_zip_income = acs_zip_income.rename(columns={
        'zip_code': 'zip',
        'population': 'acs_population',
        'median_household_income': 'acs_median_household_income',
        'poverty_universe': 'acs_poverty_universe',
        'below_poverty': 'acs_below_poverty',
        'poverty_rate': 'acs_poverty_rate',
    })
    acs_zip_income['zip'] = acs_zip_income['zip'].str.zfill(5)
    acs_zip_income = acs_zip_income[acs_columns]
    acs_zip_income = acs_zip_income[acs_zip_income['zip'].isin(sf_zips)].copy()
    print(f'ACS income after SF ZIP filtering: {len(acs_zip_income):,} rows')

    income_bracket_columns = INCOME_BRACKET_COLUMNS
    income_sum_columns = ['HH_INCOME_TOTAL'] + income_bracket_columns
    acs_bracket_columns = ['GEOID', 'YEAR_END'] + income_sum_columns
    acs_tables = []

    for file in sorted(ACS_BRACKET_DIR.glob('*.parquet')):
        table = pd.read_parquet(
            file,
            columns=acs_bracket_columns,
            filters=[('STATE_FIPS', '==', '06'), ('COUNTY_FIPS', '==', '075')]
        )
        acs_tables.append(table)

    acs_brackets = pd.concat(acs_tables, ignore_index=True)
    print(f'ACS income brackets after SF County filtering: {len(acs_brackets):,} rows')
    acs_brackets['year'] = pd.to_numeric(acs_brackets['YEAR_END'], errors='coerce')
    acs_brackets['GEOID'] = acs_brackets['GEOID'].astype('string')

    block_group_geography = gpd.read_file(f'zip://{BLOCK_GROUP_BOUNDARY_FILE}')
    block_group_geography = block_group_geography[
        block_group_geography['COUNTYFP'] == '075'
    ][['GEOID', 'geometry']]
    print(f'Block-group boundaries after SF County filtering: {len(block_group_geography):,} rows')
    block_group_geography = block_group_geography.to_crs(zip_geography.crs)

    block_group_points = block_group_geography.copy()
    block_group_points['geometry'] = block_group_points.geometry.centroid
    block_group_to_zip = gpd.sjoin(
        block_group_points,
        zip_geography[['zip_code', 'geometry']],
        how='left',
        predicate='within'
    )
    block_group_to_zip = block_group_to_zip[['GEOID', 'zip_code']]
    matched_block_groups = block_group_to_zip['zip_code'].notna().sum()
    print(f'Block groups matched to ZIPs: {matched_block_groups:,} of {len(block_group_to_zip):,} rows')
    print(f'Block groups not matched to ZIPs: {len(block_group_to_zip) - matched_block_groups:,} rows')

    acs_brackets = acs_brackets.merge(
        block_group_to_zip,
        on='GEOID',
        how='inner',
    )
    print(f'ACS income brackets after joining ZIP assignments: {len(acs_brackets):,} rows')

    for column_name in income_sum_columns:
        acs_brackets[column_name] = pd.to_numeric(
            acs_brackets[column_name],
            errors='coerce',
        )

    acs_zip_year_income = acs_brackets.groupby(['year', 'zip_code'])[income_sum_columns].sum()
    acs_zip_year_income = acs_zip_year_income.reset_index()
    print(f'ACS income brackets after summarizing by ZIP and year: {len(acs_zip_year_income):,} rows')

    acs_zip_year_income = acs_zip_year_income.rename(
        columns={'zip_code': 'zip'}
    )

    under_25k_columns = [
        'HH_INCOME_LT_10K',
        'HH_INCOME_10_15K',
        'HH_INCOME_15_20K',
        'HH_INCOME_20_25K',
    ]
    under_50k_columns = under_25k_columns + [
        'HH_INCOME_25_30K',
        'HH_INCOME_30_35K',
        'HH_INCOME_35_40K',
        'HH_INCOME_40_45K',
        'HH_INCOME_45_50K',
    ]
    over_100k_columns = [
        'HH_INCOME_100_125K',
        'HH_INCOME_125_150K',
        'HH_INCOME_150_200K',
        'HH_INCOME_GTE_200K',
    ]

    total_households = acs_zip_year_income['HH_INCOME_TOTAL']
    acs_zip_year_income['acs_share_under_25k'] = (
        acs_zip_year_income[under_25k_columns].sum(axis=1) / total_households
    )
    acs_zip_year_income['acs_share_under_50k'] = (
        acs_zip_year_income[under_50k_columns].sum(axis=1) / total_households
    )
    acs_zip_year_income['acs_share_over_100k'] = (
        acs_zip_year_income[over_100k_columns].sum(axis=1) / total_households
    )
    acs_zip_year_income['acs_share_over_200k'] = (
        acs_zip_year_income['HH_INCOME_GTE_200K'] / total_households
    )

    zip_year_socioeconomic_table = acs_zip_year_income[
        [
            'zip',
            'year',
            'HH_INCOME_TOTAL',
            'acs_share_under_25k',
            'acs_share_under_50k',
            'acs_share_over_100k',
            'acs_share_over_200k',
        ]
    ].copy()

    zip_year_socioeconomic_table = zip_year_socioeconomic_table.rename(
        columns={
            'year': 'acs_bracket_year',
            'HH_INCOME_TOTAL': 'acs_households_from_brackets',
        }
    )

    acs_bracket_features_for_model = zip_year_socioeconomic_table[
        zip_year_socioeconomic_table['acs_bracket_year'] == ACS_BLOCK_GROUP_YEAR
    ].copy()
    print(f'ACS income features after {ACS_BLOCK_GROUP_YEAR} filtering: {len(acs_bracket_features_for_model):,} rows')

    irs_year_columns = [
        'tax_year',
        'zip',
        'agi_per_return_usd',
        'wages_per_wage_return_usd',
    ]

    zip_year_socioeconomic_table = zip_year_socioeconomic_table.merge(
        irs_zip_income_by_year[irs_year_columns],
        left_on=['zip', 'acs_bracket_year'],
        right_on=['zip', 'tax_year'],
        how='left',
    )

    zip_year_socioeconomic_table = zip_year_socioeconomic_table.drop(
        columns='tax_year'
    )
    print(f'ZIP-year income data after joining IRS values: {len(zip_year_socioeconomic_table):,} rows')

    zip_socioeconomic_table = pd.DataFrame({'zip': sf_zips})

    zip_socioeconomic_table = zip_socioeconomic_table.merge(
        acs_zip_income,
        on='zip',
        how='left',
    )

    zip_socioeconomic_table = zip_socioeconomic_table.merge(
        acs_bracket_features_for_model,
        on='zip',
        how='left',
    )

    zip_socioeconomic_table = zip_socioeconomic_table.merge(
        irs_zip_income,
        on='zip',
        how='left',
    )
    print(f'ZIP socioeconomic data after ACS/IRS joins: {len(zip_socioeconomic_table):,} rows')

    return {
        'sf_irs_zip_income_2020_2022.csv': irs_zip_income_by_year,
        'sf_acs_income_brackets_by_zip_year.csv': acs_zip_year_income,
        'sf_zip_year_socioeconomic_table.csv': zip_year_socioeconomic_table,
        'sf_zip_socioeconomic_table.csv': zip_socioeconomic_table,
    }


def build_income_plot_data(income_tables, zip_geography):
    zip_socioeconomic_table = income_tables['sf_zip_socioeconomic_table.csv']
    acs_zip_year_income = income_tables['sf_acs_income_brackets_by_zip_year.csv']
    income_bracket_columns = INCOME_BRACKET_COLUMNS

    bracket_labels = [
        'Under $10k', '$10-15k', '$15-20k', '$20-25k',
        '$25-30k', '$30-35k', '$35-40k', '$40-45k',
        '$45-50k', '$50-60k', '$60-75k', '$75-100k',
        '$100-125k', '$125-150k', '$150-200k', '$200k+',
    ]

    bracket_data_2024 = acs_zip_year_income[
        acs_zip_year_income['year'] == ACS_BLOCK_GROUP_YEAR
    ].copy()
    print(f'Income-bracket plot data after {ACS_BLOCK_GROUP_YEAR} filtering: {len(bracket_data_2024):,} rows')
    box_values = []
    box_labels = []
    bracket_outliers = []

    for column_name, bracket_label in zip(income_bracket_columns, bracket_labels):
        shares = 100 * bracket_data_2024[column_name] / bracket_data_2024['HH_INCOME_TOTAL']
        first_quartile = shares.quantile(0.25)
        third_quartile = shares.quantile(0.75)
        income_iqr = third_quartile - first_quartile
        lower_fence = first_quartile - 1.5 * income_iqr
        upper_fence = third_quartile + 1.5 * income_iqr
        is_outlier = (shares < lower_fence) | (shares > upper_fence)

        if is_outlier.any():
            box_values.append(shares.to_numpy())
            box_labels.append(bracket_label)
            outliers = bracket_data_2024.loc[is_outlier, ['zip']].copy()
            outliers['share_pct'] = shares.loc[is_outlier]
            outliers['bracket'] = bracket_label
            outliers['box_position'] = len(box_values)
            bracket_outliers.append(outliers)

    bracket_outliers = pd.concat(bracket_outliers, ignore_index=True)

    box_shares = pd.DataFrame()
    for label, values in zip(box_labels, box_values):
        box_shares[label] = values
    outlier_groups = []
    for box_position, outliers in bracket_outliers.groupby('box_position'):
        outliers = outliers.reset_index(drop=True)
        for index in outliers.index:
            outliers.loc[index, 'y_position'] = (
                box_position + 0.18 * (index - (len(outliers) - 1) / 2)
            )
        outlier_groups.append(outliers)
    bracket_outliers = pd.concat(outlier_groups, ignore_index=True)

    map_features = zip_socioeconomic_table[[
        'zip', 'acs_median_household_income',
        'acs_share_under_25k', 'acs_share_over_100k'
    ]].copy()

    map_features['lower_income_rank'] = 1 - map_features['acs_share_under_25k'].rank(pct=True)
    map_features['higher_income_rank'] = map_features['acs_share_over_100k'].rank(pct=True)
    map_features['socioeconomic_score'] = (
        map_features['lower_income_rank'] + map_features['higher_income_rank']
    ) / 2

    low_cutoff = map_features['socioeconomic_score'].quantile(1 / 3)
    high_cutoff = map_features['socioeconomic_score'].quantile(2 / 3)
    map_features['socioeconomic_status'] = 'Medium'
    map_features.loc[
        map_features['socioeconomic_score'] <= low_cutoff, 'socioeconomic_status'
    ] = 'Low'
    map_features.loc[
        map_features['socioeconomic_score'] > high_cutoff, 'socioeconomic_status'
    ] = 'High'

    status_colors = {'Low': 'darkorange', 'Medium': 'goldenrod', 'High': 'seagreen'}
    map_features['map_color'] = map_features['socioeconomic_status'].map(status_colors)
    zip_map_data = zip_geography.rename(columns={'zip_code': 'zip'})
    zip_map_data = zip_map_data.merge(map_features, on='zip', how='left')

    street_edges = gpd.read_parquet(STREET_NETWORK_EDGE_FILE)
    street_edges = street_edges.to_crs(zip_map_data.crs)

    gtfs_stops = pd.read_csv(GTFS_STOPS_FILE)
    if 'location_type' in gtfs_stops.columns:
        gtfs_stops = gtfs_stops[gtfs_stops['location_type'].fillna(0) == 0].copy()
    print(f'Map stops after keeping physical stops: {len(gtfs_stops):,} rows')
    stop_geometry = gpd.points_from_xy(gtfs_stops['stop_lon'], gtfs_stops['stop_lat'])
    gtfs_stop_points = gpd.GeoDataFrame(
        gtfs_stops, geometry=stop_geometry, crs='EPSG:4326'
    )
    gtfs_stop_points = gtfs_stop_points.to_crs(zip_map_data.crs)

    sf_gtfs_stop_points = gpd.sjoin(
        gtfs_stop_points, zip_map_data[['zip', 'geometry']],
        how='inner', predicate='within'
    )
    print(f'Map stops after matching to SF ZIPs: {len(sf_gtfs_stop_points):,} rows')

    legend_rows = []
    for status in ['Low', 'Medium', 'High']:
        group = map_features[map_features['socioeconomic_status'] == status]
        min_score = group['socioeconomic_score'].min()
        max_score = group['socioeconomic_score'].max()
        min_income = group['acs_median_household_income'].min() / 1000
        max_income = group['acs_median_household_income'].max() / 1000
        legend_rows.append({
            'status': status,
            'color': status_colors[status],
            'label': (
                f'{status}: score {min_score:.2f}-{max_score:.2f}; '
                f'median income {min_income:.0f}k-{max_income:.0f}k'
            ),
        })
    xmin, ymin, xmax, ymax = zip_map_data.total_bounds
    x_padding = (xmax - xmin) * 0.03
    y_padding = (ymax - ymin) * 0.03
    bounds = pd.DataFrame([{
        'xmin': xmin - x_padding, 'xmax': xmax + x_padding,
        'ymin': ymin - y_padding, 'ymax': ymax + y_padding,
    }])
    available_columns = [
        'acs_median_household_income', 'acs_share_under_25k',
        'acs_share_under_50k', 'acs_share_over_100k', 'acs_share_over_200k',
    ]
    availability = zip_socioeconomic_table[available_columns].notna().sum()
    availability = availability.rename_axis('measure').reset_index(name='zip_count')
    tables = {
        'income_box_shares.csv': box_shares,
        'income_bracket_outliers.csv': bracket_outliers,
        'income_map_legend.csv': pd.DataFrame(legend_rows),
        'income_map_bounds.csv': bounds,
        'income_availability.csv': availability,
    }
    geography = {
        'income_zip_map.parquet': zip_map_data,
        'sf_street_edges.parquet': street_edges[['geometry']],
        'sf_transit_stops.parquet': sf_gtfs_stop_points[['stop_id', 'zip', 'geometry']],
    }
    return tables, geography


def monthly_share_cdfs(zip_months):
    observed = 100 * zip_months['observed_share']
    scheduled = 100 * zip_months['scheduled_share']
    share_values = pd.concat([observed, scheduled])
    share_values = share_values.sort_values().unique()

    rows = []
    for share in share_values:
        row = {
            'share_pct': share,
            'observed': (observed <= share).mean(),
            'scheduled': (scheduled <= share).mean()
        }
        rows.append(row)

    cdf = pd.DataFrame(rows)
    cdf['gap'] = (cdf['observed'] - cdf['scheduled']).abs()
    return cdf


def maximum_cdf_gap(cdf):
    largest_gap = cdf['gap'].max()
    tied = cdf[np.isclose(cdf['gap'], largest_gap, rtol=0, atol=1e-12)]
    return tied.sort_values('share_pct').iloc[0]


def build_arrival_tables(monthly):
    observed = monthly.copy()
    scheduled = pd.read_csv(SCHEDULE_FILE, dtype={'zip_code': 'string'})

    failed_quality_months = observed.loc[
        ~observed['data_quality_pass'], 'year_month'
    ].unique().tolist()

    observed = observed[['year_month', 'zip_code', 'observed_arrivals']].copy()
    scheduled = scheduled[['year_month', 'zip_code', 'scheduled_arrivals']].copy()


    arrivals = observed.merge(
        scheduled,
        on=['year_month', 'zip_code'],
        how='inner',
        validate='one_to_one',
    )
    print(f'Arrival comparisons after matching observed/scheduled ZIP-months: {len(arrivals):,} rows')

    month_count = arrivals['year_month'].nunique()
    zip_count = arrivals['zip_code'].nunique()
    assert len(arrivals) == month_count * zip_count
    assert (arrivals['observed_arrivals'] > 0).all()
    assert (arrivals['scheduled_arrivals'] > 0).all()

    observed_month_total = arrivals.groupby('year_month')['observed_arrivals'].transform('sum')
    scheduled_month_total = arrivals.groupby('year_month')['scheduled_arrivals'].transform('sum')

    arrivals['observed_share'] = arrivals['observed_arrivals'] / observed_month_total
    arrivals['scheduled_share'] = arrivals['scheduled_arrivals'] / scheduled_month_total
    arrivals['share_gap_pp'] = 100 * (arrivals['observed_share'] - arrivals['scheduled_share'])

    zip_results_rows = []
    cdfs = []
    gap_rows = []

    for zip_code, zip_months in arrivals.groupby('zip_code'):
        observed_shares = zip_months['observed_share']
        scheduled_shares = zip_months['scheduled_share']

        zip_part = observed_shares * np.log(observed_shares / scheduled_shares)
        rest_part = (1 - observed_shares) * np.log(
            (1 - observed_shares) / (1 - scheduled_shares)
        )
        monthly_kl = zip_part + rest_part
        ks_test = ks_2samp(observed_shares, scheduled_shares)
        cdf = monthly_share_cdfs(zip_months)
        gap = maximum_cdf_gap(cdf)

        row = {
            'zip_code': zip_code,
            'months': len(zip_months),
            'mean_observed_share_pct': 100 * observed_shares.mean(),
            'mean_scheduled_share_pct': 100 * scheduled_shares.mean(),
            'mean_share_gap_pp': 100 * (observed_shares - scheduled_shares).mean(),
            'mean_monthly_kl': monthly_kl.mean(),
            'ks_statistic': ks_test.statistic,
            'ks_gap_share_pct': gap['share_pct'],
            'ks_p_value': ks_test.pvalue
        }
        zip_results_rows.append(row)
        gap_rows.append({
            'zip_code': zip_code,
            'gap_share_pct': gap['share_pct'],
            'observed_cdf_at_gap': gap['observed'],
            'scheduled_cdf_at_gap': gap['scheduled'],
        })
        cdf['zip_code'] = zip_code
        cdfs.append(cdf)

    zip_results = pd.DataFrame(zip_results_rows)
    zip_results['direction'] = 'lower observed share'
    zip_results.loc[
        zip_results['mean_share_gap_pp'] > 0, 'direction'
    ] = 'higher observed share'
    zip_results['ks_p_05'] = zip_results['ks_p_value'] < 0.05
    zip_results = zip_results.sort_values('mean_monthly_kl', ascending=False)
    zip_results = zip_results.reset_index(drop=True)
    plot_summary = zip_results.merge(pd.DataFrame(gap_rows), on='zip_code')
    plot_summary['color'] = 'steelblue'
    plot_summary.loc[plot_summary['ks_p_05'], 'color'] = 'darkorange'
    share_gaps = plot_summary.sort_values('mean_share_gap_pp')
    selected = zip_results.sort_values(
        ['ks_p_value', 'mean_monthly_kl'], ascending=[True, False]
    ).iloc[0]
    tied = zip_results.loc[
        zip_results['ks_p_value'] == selected['ks_p_value'], 'zip_code'
    ].tolist()
    metadata = {
        'month_count': int(month_count),
        'zip_count': int(zip_count),
        'quality_flagged_months': failed_quality_months,
        'most_significant_zip': selected['zip_code'],
        'tied_lowest_p_value_zips': tied,
        'flagged_zip_codes': zip_results.loc[zip_results['ks_p_05'], 'zip_code'].tolist(),
    }
    tables = {
        'per_zip_monthly_shares.csv': arrivals,
        'per_zip_kl_ks_results.csv': zip_results,
        'monthly_share_cdfs.csv': pd.concat(cdfs, ignore_index=True),
        'arrival_plot_summary.csv': plot_summary,
        'arrival_share_gaps.csv': share_gaps,
    }
    return tables, metadata


def build_service_tables(monthly, zip_areas):
    quality_data = monthly[monthly['data_quality_pass']].copy()
    print(f'Service data after keeping quality-passing ZIP-months: {len(quality_data):,} rows')
    quality_data['stop_days'] = (
        quality_data['observed_stop_count']
        * quality_data['observed_service_days']
    )
    quality_data['weighted_delay'] = (
        quality_data['mean_delay_minutes']
        * quality_data['on_time_eligible_arrivals']
    )

    by_zip = quality_data.groupby('zip_code', as_index=False).agg(
        months_quality_pass=('year_month', 'nunique'),
        mean_bus_stop_count=('bus_stop_count', 'mean'),
        mean_stops_per_sqmi=('stops_per_sqmi', 'mean'),
        mean_stops_per_1000_residents=('stops_per_1000_residents', 'mean'),
        scheduled_arrivals=('scheduled_arrivals', 'sum'),
        observed_arrivals=('observed_arrivals', 'sum'),
        stop_days=('stop_days', 'sum'),
        on_time_arrivals=('on_time_arrivals', 'sum'),
        eligible_arrivals=('on_time_eligible_arrivals', 'sum'),
        weighted_delay=('weighted_delay', 'sum'),
    )
    context_columns = [
        'zip_code', 'area_sqmi', 'quarter_mile_stop_coverage_pct_2026',
        'acs_year', 'population', 'median_household_income',
        'poverty_universe', 'below_poverty', 'poverty_rate',
    ]
    context = monthly[context_columns].drop_duplicates('zip_code')
    print(f'ZIP context after removing duplicate ZIPs: {len(context):,} rows')
    by_zip = context.merge(by_zip, on='zip_code', how='left')
    print(f'Service data after summarizing and joining ZIP context: {len(by_zip):,} rows')
    by_zip['observed_arrivals_per_stop_per_day'] = (
        by_zip['observed_arrivals'] / by_zip['stop_days']
    )
    by_zip['observed_arrivals_pct_of_scheduled'] = (
        100 * by_zip['observed_arrivals'] / by_zip['scheduled_arrivals']
    )
    by_zip['on_time_pct'] = (
        100 * by_zip['on_time_arrivals'] / by_zip['eligible_arrivals']
    )
    by_zip['mean_delay_minutes'] = (
        by_zip['weighted_delay'] / by_zip['eligible_arrivals']
    )
    by_zip = by_zip.drop(columns=['stop_days', 'weighted_delay'])

    city = quality_data.groupby('year_month', as_index=False).agg(
        arrivals=('observed_arrivals', 'sum'),
        stop_days=('stop_days', 'sum'),
        on_time=('on_time_arrivals', 'sum'),
        eligible=('on_time_eligible_arrivals', 'sum'),
    )
    city['arrivals_per_stop_per_day'] = city['arrivals'] / city['stop_days']
    city['on_time_pct'] = 100 * city['on_time'] / city['eligible']
    print(f'City service after summarizing quality-passing months: {len(city):,} rows')

    pairs = [
        ('median_household_income', 'observed_arrivals_per_stop_per_day'),
        ('median_household_income', 'on_time_pct'),
        ('poverty_rate', 'observed_arrivals_per_stop_per_day'),
        ('poverty_rate', 'on_time_pct'),
        ('mean_stops_per_sqmi', 'observed_arrivals_per_stop_per_day'),
        ('mean_stops_per_1000_residents', 'observed_arrivals_per_stop_per_day'),
        ('quarter_mile_stop_coverage_pct_2026', 'observed_arrivals_per_stop_per_day'),
    ]
    results = []
    for first, second in pairs:
        complete = by_zip[[first, second]].dropna()
        print(f'Complete ZIP rows for {first} vs {second}: {len(complete):,} rows')
        correlation, p_value = pearsonr(complete[first], complete[second])
        results.append(
            {
                'first_variable': first,
                'second_variable': second,
                'correlation': correlation,
                'p_value': p_value,
                'zip_count': len(complete),
            }
        )
    correlations = pd.DataFrame(results)

    model_columns = [
        'observed_arrivals_per_stop_per_day', 'on_time_pct',
        'mean_stops_per_sqmi', 'mean_stops_per_1000_residents',
        'median_household_income', 'poverty_rate',
    ]
    model_data = by_zip.dropna(subset=model_columns).copy()
    print(f'Regression data after removing incomplete ZIPs: {len(model_data):,} rows')
    model_data['income_in_thousands'] = model_data['median_household_income'] / 1000
    model_rows = []
    for outcome in ['observed_arrivals_per_stop_per_day', 'on_time_pct']:
        for access in ['mean_stops_per_sqmi', 'mean_stops_per_1000_residents']:
            formula = f'{outcome} ~ {access} + income_in_thousands + poverty_rate'
            model = smf.ols(formula, data=model_data).fit()
            intervals = model.conf_int()
            for term in model.params.index:
                model_rows.append({
                    'outcome': outcome, 'access_measure': access, 'term': term,
                    'estimate': model.params[term], 'std_error': model.bse[term],
                    'p_value': model.pvalues[term],
                    'ci_95_low': intervals.loc[term, 0],
                    'ci_95_high': intervals.loc[term, 1],
                    'r_squared': model.rsquared, 'n': int(model.nobs),
                })

    income_service = by_zip[by_zip['zip_code'] != '94104'].copy()
    print(f'Income/service chart data after excluding ZIP 94104: {len(income_service):,} rows')
    income_service = income_service.rename(columns={
        'mean_stops_per_1000_residents': 'stops_per_1000_residents',
        'observed_arrivals_per_stop_per_day': 'arrivals_per_stop_per_day',
    })
    income_service = income_service.sort_values('median_household_income')
    income_labels = []
    for row in income_service.itertuples():
        income_labels.append(f'{row.zip_code} ({row.median_household_income / 1000:.0f}k)')
    income_service['income_label'] = income_labels

    label_zips = ['94108', '94105', '94103', '94158', '94124', '94127']
    chart_labels = income_service[income_service['zip_code'].isin(label_zips)].copy()
    chart_labels['label_x'] = chart_labels['stops_per_1000_residents'] + 0.1
    chart_labels['label_y'] = chart_labels['arrivals_per_stop_per_day']

    measures = [
        'mean_stops_per_sqmi', 'mean_stops_per_1000_residents',
        'quarter_mile_stop_coverage_pct_2026', 'observed_arrivals_per_stop_per_day',
        'observed_arrivals_pct_of_scheduled', 'on_time_pct', 'mean_delay_minutes',
        'median_household_income', 'poverty_rate',
    ]
    summary = by_zip[measures].describe()
    summary = summary.rename_axis('statistic').reset_index()
    metadata = {
        'stops_frequency_spearman': float(income_service['stops_per_1000_residents'].corr(
            income_service['arrivals_per_stop_per_day'], method='spearman'
        )),
        'income_ontime_spearman': float(income_service['median_household_income'].corr(
            income_service['on_time_pct'], method='spearman'
        )),
        'income_service_zip_count': int(len(income_service)),
    }
    tables = {
        'zip_service_summary.csv': by_zip,
        'monthly_service_summary.csv': city,
        'service_correlations.csv': correlations,
        'service_model_coefficients.csv': pd.DataFrame(model_rows),
        'income_service_charts.csv': income_service,
        'service_chart_labels.csv': chart_labels,
        'service_summary_statistics.csv': summary,
    }
    service_map = zip_areas.merge(by_zip, on='zip_code', how='left')
    return tables, service_map, metadata


def file_content(path):
    content = path.read_bytes()
    if path.suffix in {'.csv', '.txt', '.json'}:
        content = content.replace(b'\r\n', b'\n')
    return content


def write_notebook_manifest(tables, geography):
    output_rows = {'analysis_metadata.json': None}
    output_rows.update({filename: len(table) for filename, table in tables.items()})
    output_rows.update({filename: len(data) for filename, data in geography.items()})
    files = []
    for filename in sorted(output_rows):
        path = NOTEBOOK_DIR / filename
        content = file_content(path)
        details = {
            'path': path.relative_to(ROOT).as_posix(),
            'bytes': len(content),
            'sha256': hashlib.sha256(content).hexdigest(),
        }
        if output_rows[filename] is not None:
            details['rows'] = output_rows[filename]
        files.append(details)
    builder_content = file_content(Path(__file__))
    manifest = {
        'notebook': 'notebooks/sf_income_and_arrival_analysis.ipynb',
        'builder': 'data_cleaning/build_dataset.py',
        'builder_sha256': hashlib.sha256(builder_content).hexdigest(),
        'text_line_endings': 'LF for CSV and JSON',
        'files': files,
    }
    NOTEBOOK_MANIFEST.write_text(
        json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n'
    )


def build_notebook_data(monthly, zip_areas):
    NOTEBOOK_DIR.mkdir(parents=True, exist_ok=True)
    zip_geography = zip_areas[['zip_code', 'geometry']].to_crs('EPSG:26910')
    income_tables = build_income_tables(zip_geography)
    plot_tables, geography = build_income_plot_data(income_tables, zip_geography)
    arrival_tables, metadata = build_arrival_tables(monthly)
    service_tables, service_map, service_metadata = build_service_tables(monthly, zip_areas)

    tables = {}
    tables.update(income_tables)
    tables.update(plot_tables)
    tables.update(arrival_tables)
    tables.update(service_tables)
    for filename, table in tables.items():
        table.to_csv(NOTEBOOK_DIR / filename, index=False)
        print(f'Saved {filename}: {len(table):,} rows')
    geography['service_zip_map.parquet'] = service_map
    for filename, data in geography.items():
        data.to_parquet(NOTEBOOK_DIR / filename, index=False)
        print(f'Saved {filename}: {len(data):,} rows')
    metadata.update(service_metadata)
    (NOTEBOOK_DIR / 'analysis_metadata.json').write_text(
        json.dumps(metadata, indent=2), encoding='utf-8', newline='\n'
    )
    write_notebook_manifest(tables, geography)
    print(f'Saved {len(tables)} cleaned tables and {len(geography)} map layers to {NOTEBOOK_DIR}')


def main():
    zip_areas = load_zip_areas()
    transit = load_checkpoints()
    if transit.empty:
        return

    if not SCHEDULE_FILE.is_file():
        rebuild_sfmta_schedule()
    schedule = pd.read_csv(SCHEDULE_FILE, dtype={'zip_code': 'string'})
    walk_coverage = build_walk_coverage(zip_areas)
    acs = pd.read_csv(ACS_FILE, dtype={'zip_code': 'string'})
    data = build_dataset(transit, schedule, zip_areas, walk_coverage, acs)
    completed = sorted(data['year_month'].unique())
    expected = month_range(START_MONTH, END_MONTH)
    complete = len(completed) == len(expected)
    CLEANED_DIR.mkdir(parents=True, exist_ok=True)
    complete_path = CLEANED_DIR / 'sf_zip_month_transit.csv'
    partial_path = CLEANED_DIR / 'sf_zip_month_transit_partial.csv'
    output = complete_path if complete else partial_path
    old_output = partial_path if complete else complete_path
    old_output.unlink(missing_ok=True)
    data.to_csv(output, index=False)
    print(f'Saved {output.name}: {len(data):,} rows')
    if complete:
        build_notebook_data(data, zip_areas)
        return output
    else:
        print('Notebook tables require the complete study period.')
        return None


def map_schedule_stops_to_zips(stops, relevant_stop_ids, zip_areas):
    selected = stops[stops['stop_id'].astype(str).isin(relevant_stop_ids)].copy()
    selected['stop_lon'] = pd.to_numeric(selected['stop_lon'], errors='coerce')
    selected['stop_lat'] = pd.to_numeric(selected['stop_lat'], errors='coerce')
    selected = selected.dropna(subset=['stop_lon', 'stop_lat'])
    points = gpd.GeoDataFrame(
        selected[['stop_id']],
        geometry=gpd.points_from_xy(selected['stop_lon'], selected['stop_lat']),
        crs='EPSG:4326',
    ).to_crs(zip_areas.crs)
    joined = gpd.sjoin(
        points,
        zip_areas[['zip_code', 'geometry']],
        how='inner',
        predicate='intersects',
    ).drop_duplicates('stop_id')
    return dict(zip(joined['stop_id'].astype(str), joined['zip_code']))

def find_member(archive, filename):
    matches = [
        name for name in archive.namelist()
        if name.rsplit('/', 1)[-1].lower() == filename.lower()
    ]
    if not matches:
        raise FileNotFoundError(f'{filename} not found in {archive.filename}')
    if len(matches) > 1:
        raise ValueError(f'Multiple {filename} entries found in {archive.filename}')
    return matches[0]


def read_zip_csv(archive, filename, usecols=None):
    with archive.open(find_member(archive, filename)) as handle:
        return pd.read_csv(handle, dtype='string', usecols=usecols, low_memory=False)


def identify_bus_trips(routes, trips):
    required_routes = {'route_id', 'route_type'}
    required_trips = {'trip_id', 'route_id', 'service_id'}
    missing = required_routes.difference(routes.columns)
    if missing:
        raise ValueError(f'routes.txt is missing columns: {sorted(missing)}')
    missing = required_trips.difference(trips.columns)
    if missing:
        raise ValueError(f'trips.txt is missing columns: {sorted(missing)}')

    route_ids = routes['route_id'].astype('string')
    route_type = pd.to_numeric(routes['route_type'], errors='coerce')
    if 'agency_id' in routes.columns:
        agency = routes['agency_id'].fillna('').str.upper()
        sf_operator = agency.isin(SF_AGENCY_IDS) | route_ids.str.upper().str.startswith('SF:')
    else:
        sf_operator = route_ids.str.upper().str.startswith('SF:')
    bus_routes = set(route_ids.loc[sf_operator & route_type.eq(BUS_ROUTE_TYPE)].dropna())
    if not bus_routes:
        raise ValueError('No SFMTA bus routes found; inspect agency_id and route_id values')
    return trips.loc[
        trips['route_id'].isin(bus_routes), ['trip_id', 'service_id']
    ].drop_duplicates()


def service_days_by_month(calendar, calendar_dates):
    weekdays = (
        'monday', 'tuesday', 'wednesday', 'thursday',
        'friday', 'saturday', 'sunday',
    )
    regular_days = []
    if calendar is not None and not calendar.empty:
        for row in calendar.itertuples(index=False):
            service_id = str(row.service_id)
            dates = pd.date_range(
                pd.to_datetime(str(row.start_date).split('.')[0], format='%Y%m%d'),
                pd.to_datetime(str(row.end_date).split('.')[0], format='%Y%m%d'),
            )
            flags = [str(getattr(row, day)).split('.')[0] == '1' for day in weekdays]
            dates = [date for date in dates if flags[date.weekday()]]
            regular_days.extend((service_id, date) for date in dates)

    active = pd.DataFrame(regular_days, columns=['service_id', 'date'])
    if calendar_dates is not None and not calendar_dates.empty:
        exceptions = calendar_dates[['service_id', 'date', 'exception_type']].copy()
        exceptions['service_id'] = exceptions['service_id'].astype(str)
        exceptions['date'] = pd.to_datetime(
            exceptions['date'].astype(str).str.split('.').str[0],
            format='%Y%m%d',
        )
        additions = exceptions[exceptions['exception_type'].astype(str).str.startswith('1')]
        removals = exceptions[exceptions['exception_type'].astype(str).str.startswith('2')]
        active = pd.concat(
            [active, additions[['service_id', 'date']]], ignore_index=True
        ).drop_duplicates()
        if not removals.empty:
            removal_keys = pd.MultiIndex.from_frame(removals[['service_id', 'date']])
            active_keys = pd.MultiIndex.from_frame(active[['service_id', 'date']])
            active = active[~active_keys.isin(removal_keys)]

    if active.empty:
        return pd.DataFrame(columns=['service_id', 'year_month', 'active_days'])
    active['date'] = pd.to_datetime(active['date'])
    active['year_month'] = active['date'].dt.to_period('M').astype(str)
    return (
        active.groupby(['service_id', 'year_month'])
        .size()
        .reset_index(name='active_days')
    )


def stop_month_schedule(stop_time_chunks, bus_trips, service_days):
    counts = []
    for chunk in stop_time_chunks:
        selected = chunk[['trip_id', 'stop_id']].merge(
            bus_trips, on='trip_id', how='inner'
        )
        if selected.empty:
            continue
        counts.append(
            selected.groupby(['stop_id', 'service_id'])
            .size()
            .reset_index(name='daily_arrivals')
        )
    if not counts or service_days.empty:
        return pd.DataFrame(columns=['year_month', 'stop_id', 'scheduled_arrivals'])
    stop_service = (
        pd.concat(counts)
        .groupby(['stop_id', 'service_id'], as_index=False)['daily_arrivals']
        .sum()
    )
    scheduled = stop_service.merge(service_days, on='service_id', how='inner')
    scheduled = scheduled[
        scheduled['year_month'].between(STUDY_START_MONTH, STUDY_END_MONTH)
    ].copy()
    scheduled['scheduled_arrivals'] = (
        scheduled['daily_arrivals'] * scheduled['active_days']
    )
    return scheduled.groupby(
        ['year_month', 'stop_id'], as_index=False
    )['scheduled_arrivals'].sum()

def schedule_by_zip(stop_schedule, stop_to_zip):
    mapped = stop_schedule.assign(
        zip_code=stop_schedule['stop_id'].map(stop_to_zip)
    ).dropna(
        subset=['zip_code']
    )
    return (
        mapped.groupby(['year_month', 'zip_code'], as_index=False)
        .agg(
            bus_stop_count=('stop_id', 'nunique'),
            scheduled_arrivals=('scheduled_arrivals', 'sum'),
        )
        .sort_values(['year_month', 'zip_code'])
    )


def process_schedule_archive(archive_path, zip_areas, target_months):
    print(f'Processing {archive_path.name}', flush=True)
    with zipfile.ZipFile(archive_path) as archive:
        routes = read_zip_csv(archive, 'routes.txt')
        trips = read_zip_csv(archive, 'trips.txt', ['trip_id', 'route_id', 'service_id'])
        bus_trips = identify_bus_trips(routes, trips)
        service_days = service_days_by_month(
            read_zip_csv(archive, 'calendar.txt')
            if any(name.rsplit('/', 1)[-1] == 'calendar.txt' for name in archive.namelist())
            else None,
            read_zip_csv(archive, 'calendar_dates.txt')
            if any(name.rsplit('/', 1)[-1] == 'calendar_dates.txt' for name in archive.namelist())
            else None,
        )
        stop_times = pd.read_csv(
            archive.open(find_member(archive, 'stop_times.txt')),
            dtype='string',
            usecols=['trip_id', 'stop_id'],
            chunksize=CHUNK_SIZE,
        )
        stop_schedule = stop_month_schedule(stop_times, bus_trips, service_days)
        if stop_schedule.empty:
            return pd.DataFrame(
                columns=[
                    'year_month',
                    'zip_code',
                    'bus_stop_count',
                    'scheduled_arrivals',
                ]
            )
        relevant_stops = set(stop_schedule['stop_id'])
        stops = read_zip_csv(archive, 'stops.txt', ['stop_id', 'stop_lon', 'stop_lat'])
        stop_to_zip = map_schedule_stops_to_zips(stops, relevant_stops, zip_areas)
        schedule = schedule_by_zip(stop_schedule, stop_to_zip)
        return schedule.loc[schedule['year_month'].isin(target_months)].copy()

def source_archive(month, source_dir):
    name = 'sfmta_2022-09.zip' if month in FALLBACK_MONTHS else f'regional_gtfs_{month}.zip'
    path = source_dir / name
    if not path.is_file():
        raise FileNotFoundError(f'Missing schedule source archive: {path}')
    if not zipfile.is_zipfile(path):
        raise ValueError(f'Invalid GTFS archive (run git lfs pull): {path}')
    return path


def build_schedule(source_dir=SCHEDULE_SOURCE_DIR):
    months = month_range(STUDY_START_MONTH, STUDY_END_MONTH)
    zip_areas = load_zip_areas()
    months_by_archive = {}
    for month in months:
        archive = source_archive(month, source_dir)
        months_by_archive.setdefault(archive, set()).add(month)

    frames = []
    for archive, target_months in months_by_archive.items():
        frame = process_schedule_archive(archive, zip_areas, target_months)
        if frame.empty:
            raise RuntimeError(f'No SFMTA bus schedule rows in {archive.name}')
        frames.append(frame)
    schedule = pd.concat(frames, ignore_index=True)
    schedule = schedule.drop_duplicates(['year_month', 'zip_code'])
    grid = pd.MultiIndex.from_product(
        [months, sorted(zip_areas['zip_code'])], names=['year_month', 'zip_code']
    ).to_frame(index=False)
    output = grid.merge(schedule, on=['year_month', 'zip_code'], how='left')
    output['bus_stop_count'] = output['bus_stop_count'].fillna(0).astype(int)
    output['scheduled_arrivals'] = output['scheduled_arrivals'].fillna(0).astype(int)
    area_table = pd.read_csv(ZIP_FILE, dtype='string')
    zip_column = 'zip_code' if 'zip_code' in area_table.columns else 'zip'
    area_table['zip_code'] = (
        area_table[zip_column].str.replace(r'\.0$', '', regex=True).str.zfill(5)
    )
    area_table['sqmi'] = pd.to_numeric(
        area_table['sqmi'].str.replace(',', ''), errors='coerce'
    )
    areas = area_table.groupby('zip_code')['sqmi'].sum()
    output['area_sqmi'] = output['zip_code'].map(areas)
    output['stops_per_sqmi'] = output['bus_stop_count'] / output['area_sqmi']
    output['scheduled_arrivals_per_stop'] = (
        output['scheduled_arrivals'] / output['bus_stop_count'].replace(0, pd.NA)
    )
    return output.sort_values(['year_month', 'zip_code']).reset_index(drop=True)


def rebuild_sfmta_schedule(source_dir=SCHEDULE_SOURCE_DIR, output=SCHEDULE_FILE):
    schedule = build_schedule(source_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    schedule.to_csv(output, index=False)
    print(f'Saved {output.name}: {len(schedule):,} rows')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Build cleaned notebook data or the raw SFMTA schedule snapshot'
    )
    parser.add_argument(
        '--build-schedule', action='store_true',
        help='Rebuild the schedule CSV from archived GTFS sources',
    )
    parser.add_argument('--schedule-source-dir', type=Path, default=SCHEDULE_SOURCE_DIR)
    parser.add_argument('--schedule-output', type=Path, default=SCHEDULE_FILE)
    args = parser.parse_args()
    if args.build_schedule:
        rebuild_sfmta_schedule(args.schedule_source_dir, args.schedule_output)
    else:
        main()
