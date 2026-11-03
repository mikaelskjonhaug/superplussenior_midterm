import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

from data_cleaning.build_dataset import (
    CHUNK_SIZE,
    MONTHLY_DIR,
    get_bus_routes,
    load_zip_areas,
)


def map_stops_to_zips(stops, zip_areas):
    stops = stops.copy()
    stops['stop_lon'] = pd.to_numeric(stops['stop_lon'], errors='coerce')
    stops['stop_lat'] = pd.to_numeric(stops['stop_lat'], errors='coerce')
    stops = stops.dropna(subset=['stop_lon', 'stop_lat'])
    print(f'511 stops after removing invalid coordinates: {len(stops):,} rows')
    points = gpd.GeoDataFrame(
        {'stop_id': stops['stop_id'].astype(str)},
        geometry=gpd.points_from_xy(stops['stop_lon'], stops['stop_lat']),
        crs='EPSG:4326',
    ).to_crs(zip_areas.crs)
    joined = gpd.sjoin(
        points,
        zip_areas[['zip_code', 'geometry']],
        how='inner',
        predicate='intersects',
    )
    print(f'511 stops after matching to ZIPs: {len(joined):,} rows')
    joined = joined.drop_duplicates('stop_id')
    print(f'511 stops after removing duplicate stop IDs: {len(joined):,} rows')
    return dict(zip(joined['stop_id'], joined['zip_code']))


def time_to_seconds(values):
    text = values.astype('string').str.strip()
    seconds = pd.to_numeric(text, errors='coerce')
    seconds = seconds.where(seconds >= 0)
    time_parts = text.str.extract(r'^(\d{1,3}):([0-5]\d):([0-5]\d)$')
    time_parts = time_parts.apply(pd.to_numeric, errors='coerce')
    clock_seconds = time_parts[0] * 3600 + time_parts[1] * 60 + time_parts[2]
    return seconds.fillna(clock_seconds)


def clean_chunk(chunk, month, bus_routes, stop_to_zip, stop_column, date_column):
    selected = chunk[chunk['route_id'].isin(bus_routes)].copy()
    if 'schedule_relationship' in selected.columns:
        excluded = ['1', '2', 'SKIPPED', 'NO_DATA', 'CANCELED']
        relationship = selected['schedule_relationship'].fillna('').str.upper()
        selected = selected[~relationship.isin(excluded)]

    selected = selected.drop_duplicates(['trip_id', date_column, stop_column])
    selected['zip_code'] = selected[stop_column].map(stop_to_zip)
    selected['service_month'] = (
        selected[date_column].str[:4] + '-' + selected[date_column].str[4:6]
    )
    selected['observed_seconds'] = time_to_seconds(selected['observed_arrival_time'])
    selected['scheduled_seconds'] = time_to_seconds(selected['scheduled_arrival_time'])
    valid_date = selected[date_column].str.fullmatch(r'\d{8}', na=False)
    selected = selected[
        selected['zip_code'].notna()
        & valid_date
        & selected['observed_seconds'].notna()
        & selected['service_month'].eq(month)
    ].copy()
    return selected


def process_month(path, month, zip_areas):
    summaries = []
    stop_pairs = []
    day_pairs = []
    with zipfile.ZipFile(path) as archive:
        files = {Path(name).name.lower(): name for name in archive.namelist()}
        needed = ['routes.txt', 'stops.txt', 'stop_observations.txt']
        if any(name not in files for name in needed):
            print(f'{month} cleaned ZIP summary: 0 rows (required archive files are missing)')
            return pd.DataFrame()

        routes = pd.read_csv(archive.open(files['routes.txt']), dtype='string')
        bus_routes = get_bus_routes(routes)
        stops = pd.read_csv(
            archive.open(files['stops.txt']),
            dtype='string',
            usecols=['stop_id', 'stop_lon', 'stop_lat'],
        )
        longitude = pd.to_numeric(stops['stop_lon'], errors='coerce')
        latitude = pd.to_numeric(stops['stop_lat'], errors='coerce')
        stops = stops[
            longitude.between(-122.53, -122.34) & latitude.between(37.70, 37.84)
        ]
        print(f'{month} stops after SF coordinate bounds filtering: {len(stops):,} rows')
        stop_to_zip = map_stops_to_zips(stops, zip_areas)

        observations = files['stop_observations.txt']
        header = pd.read_csv(archive.open(observations), nrows=0).columns
        stop_column = 'stop_id' if 'stop_id' in header else 'to_stop_id'
        date_column = (
            'trip_start_date' if 'trip_start_date' in header else 'service_date'
        )
        columns = [
            'trip_id',
            'route_id',
            stop_column,
            date_column,
            'schedule_relationship',
            'scheduled_arrival_time',
            'observed_arrival_time',
        ]
        columns = [column for column in columns if column in header]
        chunks = pd.read_csv(
            archive.open(observations),
            dtype='string',
            usecols=columns,
            chunksize=CHUNK_SIZE,
            low_memory=False,
        )

        for chunk in chunks:
            selected = clean_chunk(
                chunk,
                month,
                bus_routes,
                stop_to_zip,
                stop_column,
                date_column,
            )
            if selected.empty:
                continue

            delay = selected['observed_seconds'] - selected['scheduled_seconds']
            delay = delay.where(delay > -43200, delay + 86400)
            delay = delay.where(delay < 43200, delay - 86400)
            selected['delay_seconds'] = delay
            selected['has_schedule'] = selected['scheduled_seconds'].notna()
            selected['on_time'] = delay.between(-60, 300)
            summaries.append(
                selected.groupby('zip_code', as_index=False).agg(
                    observed_arrivals=('trip_id', 'size'),
                    on_time_eligible_arrivals=('has_schedule', 'sum'),
                    on_time_arrivals=('on_time', 'sum'),
                    delay_seconds=('delay_seconds', 'sum'),
                )
            )
            stop_pairs.append(selected[['zip_code', stop_column]].drop_duplicates())
            day_pairs.append(selected[['zip_code', date_column]].drop_duplicates())

    if not summaries:
        print(f'{month} cleaned ZIP summary: 0 rows (no valid observations)')
        return pd.DataFrame()

    data = pd.concat(summaries).groupby('zip_code', as_index=False).sum()
    stop_counts = (
        pd.concat(stop_pairs)
        .drop_duplicates()
        .groupby('zip_code')
        .size()
        .rename('observed_stop_count')
    )
    day_counts = (
        pd.concat(day_pairs)
        .drop_duplicates()
        .groupby('zip_code')
        .size()
        .rename('observed_service_days')
    )
    data = data.merge(stop_counts, on='zip_code').merge(day_counts, on='zip_code')
    data['year_month'] = month
    data['on_time_pct'] = (
        100 * data['on_time_arrivals'] / data['on_time_eligible_arrivals']
    )
    data['mean_delay_minutes'] = data['delay_seconds'] / (
        60 * data['on_time_eligible_arrivals']
    )
    columns = [
        'year_month',
        'zip_code',
        'observed_stop_count',
        'observed_service_days',
        'observed_arrivals',
        'on_time_eligible_arrivals',
        'on_time_arrivals',
        'on_time_pct',
        'mean_delay_minutes',
    ]
    data = data[columns].sort_values('zip_code').reset_index(drop=True)
    print(f'{month} observations after summarizing by ZIP: {len(data):,} rows')
    return data


def clean_month(path, month):
    data = process_month(Path(path), month, load_zip_areas())
    if data.empty:
        return None
    output = MONTHLY_DIR / f'transit_{month}.csv'
    data.to_csv(output, index=False)
    print(f'Saved {output.name}: {len(data):,} rows')
    return output
