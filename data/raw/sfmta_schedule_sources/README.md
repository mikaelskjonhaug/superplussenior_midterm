# Historical SFMTA schedule sources

This folder contains the GTFS schedule source files needed to regenerate
`../../cleaned/sf_zip_month_schedule_sfmta_history.csv`. There are 50 monthly Regional
GTFS bundles provided by [511 SF Bay](https://511.org/open-data/transit),
covering the months from March 2022 through September 2026 for which the
Regional archive contains SFMTA bus schedules. The direct SFMTA fall 2022
bundle supplies August through December 2022, when the Regional archives
did not contain the SFMTA schedule used by the original generator.

Each ZIP contains only the GTFS members used by the schedule generator:
`routes.txt`, `trips.txt`, `calendar.txt` when present,
`calendar_dates.txt`, `stop_times.txt`, and `stops.txt`. Their file contents
are unchanged from the downloaded archives. The large observation files and
other members were omitted because they do not contribute to the schedule
table. `member_hashes.json` records the uncompressed SHA-256 checksum of each
retained member.

The Regional archive endpoint uses `operator_id=RG` and
`historic=YYYY-MM` at `https://api.511.org/transit/datafeeds` with a 511 API
token. The fall 2022 SFMTA bundle came from the archived feed at
`https://openmobilitydata-data.s3.us-west-1.amazonaws.com/public/feeds/sfmta/60/20220926/gtfs.zip`.
`scripts/package_schedule_sources.py` records how the schedule members were
retained from the downloaded archive cache.

Data provided by [511.org](https://511.org). Use of the Regional source data
is subject to the [511 Data Disseminator Agreement](https://511.org/sites/default/files/2026-04/511_Data_Agreement_Final_2026.pdf).
SFMTA transit data and derivatives are subject to the
[SFMTA transit data license](../SFMTA_GTFS_20260829_20270115v2/SFMTA_Transit_Data_License_Agreement.txt).

Reproduced with permission granted by the City and County of San Francisco.
The information has been provided by means of a nonexclusive, limited, and
revocable license granted by the City and County of San Francisco.

The City and County of San Francisco does not guarantee the accuracy,
adequacy, completeness or usefulness of any information. The City and County
of San Francisco provides this information "as is," without warranty of any
kind, express or implied, including but not limited to warranties of
merchantability or fitness for a particular purpose, and assumes no
responsibility for anyone's use of the information.
