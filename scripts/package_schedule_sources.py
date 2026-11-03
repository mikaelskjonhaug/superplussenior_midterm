"""Keep the unchanged GTFS schedule members needed for the ZIP-month table.

Run this once against the locally downloaded 511 archive cache. It removes
unrelated observation and auxiliary files from the archive bundles without
changing the contents of any retained GTFS file.
"""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / 'data/raw/sfmta_schedule_sources'
MEMBERS = ('routes.txt', 'trips.txt', 'calendar.txt', 'calendar_dates.txt', 'stop_times.txt', 'stops.txt')
FALLBACK_MONTHS = {'2022-08', '2022-09', '2022-10', '2022-11', '2022-12'}


def copy_member(source, target, member):
    digest = hashlib.sha256()
    with source.open(member) as reader, target.open(Path(member.filename).name, 'w', force_zip64=True) as writer:
        while chunk := reader.read(4 * 1024 * 1024):
            writer.write(chunk)
            digest.update(chunk)
    return {'bytes': member.file_size, 'sha256': digest.hexdigest()}


def package_archive(source_path, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix('.zip.part')
    files = {}
    with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(
        temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6,
        allowZip64=True,
    ) as target:
        members = {Path(info.filename).name.lower(): info for info in source.infolist()}
        required = {'routes.txt', 'trips.txt', 'stop_times.txt', 'stops.txt'}
        missing = required - set(members)
        if missing or not {'calendar.txt', 'calendar_dates.txt'} & set(members):
            raise ValueError(f'{source_path} lacks required schedule files: {sorted(missing)}')
        for filename in MEMBERS:
            if filename in members:
                files[filename] = copy_member(source, target, members[filename])
    temporary.replace(output_path)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_dir', type=Path, help='Directory containing regional_gtfs_YYYY-MM.zip and sfmta_2022-09.zip')
    parser.add_argument('--output-dir', type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    months = [f'{year}-{month:02d}' for year in range(2022, 2027) for month in range(1, 13)]
    months = [month for month in months if '2022-03' <= month <= '2026-09']
    sources = {f'regional_gtfs_{month}.zip' for month in months if month not in FALLBACK_MONTHS}
    sources.add('sfmta_2022-09.zip')
    manifest = {}
    for filename in sorted(sources):
        source_path = args.source_dir / filename
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        output_path = args.output_dir / filename
        if output_path.exists():
            raise FileExistsError(output_path)
        print(f'Packaging {filename}', flush=True)
        manifest[filename] = package_archive(source_path, output_path)
    (args.output_dir / 'member_hashes.json').write_text(
        json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n'
    )
    print(f'Wrote {len(sources)} schedule source archives to {args.output_dir}')


if __name__ == '__main__':
    main()
