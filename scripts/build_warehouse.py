"""Build the local warehouse: download NYC taxi data, shape it into 3 tables.

Run once:  python scripts/build_warehouse.py

Downloads ~50 MB and produces a ~40 MB DuckDB file. Everything after this runs
entirely offline.

The data is real: NYC Taxi & Limousine Commission trip records, January 2024.
Real data matters here — the agent has to cope with NULLs, absurd outliers, and
a zone lookup that doesn't perfectly join. Synthetic data would hide exactly the
failures this repo is about.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataagent.config import DATA_DIR, WAREHOUSE_PATH

TRIPS_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-01.parquet"
ZONES_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"

SAMPLE_ROWS = 300_000  # enough to be interesting, small enough to stay snappy


def download(url: str, dest: Path) -> Path:
    if dest.exists():
        print(f"  ✓ {dest.name} already downloaded")
        return dest
    print(f"  ↓ {url.rsplit('/', 1)[-1]} ...", end="", flush=True)
    urllib.request.urlretrieve(url, dest)
    print(f" {dest.stat().st_size / 1e6:.1f} MB")
    return dest


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading NYC taxi data")
    trips_parquet = download(TRIPS_URL, DATA_DIR / "yellow_tripdata_2024-01.parquet")
    zones_csv = download(ZONES_URL, DATA_DIR / "taxi_zone_lookup.csv")

    if WAREHOUSE_PATH.exists():
        WAREHOUSE_PATH.unlink()

    print("\nBuilding warehouse")
    con = duckdb.connect(str(WAREHOUSE_PATH))

    con.execute(f"""
        CREATE TABLE trips AS
        SELECT
            VendorID                             AS vendor_id,
            tpep_pickup_datetime                 AS pickup_at,
            tpep_dropoff_datetime                AS dropoff_at,
            passenger_count::INTEGER             AS passenger_count,
            trip_distance                        AS trip_distance_miles,
            PULocationID                         AS pickup_zone_id,
            DOLocationID                         AS dropoff_zone_id,
            payment_type::INTEGER                AS payment_type_id,
            fare_amount, tip_amount, tolls_amount, total_amount
        FROM read_parquet('{trips_parquet}')
        WHERE tpep_pickup_datetime >= DATE '2024-01-01'
          AND tpep_pickup_datetime <  DATE '2024-02-01'
        LIMIT {SAMPLE_ROWS};
    """)
    print(f"  ✓ trips  ({con.execute('SELECT count(*) FROM trips').fetchone()[0]:,} rows)")

    con.execute(f"""
        CREATE TABLE zones AS
        SELECT LocationID AS zone_id, Borough AS borough, Zone AS zone_name,
               service_zone
        FROM read_csv_auto('{zones_csv}');
    """)
    print(f"  ✓ zones  ({con.execute('SELECT count(*) FROM zones').fetchone()[0]:,} rows)")

    # A tiny lookup the agent must learn to join. Payment type is an integer in
    # the raw data and meaningless without this table — a good first test of
    # whether the agent reads the schema or guesses.
    con.execute("""
        CREATE TABLE payment_types (payment_type_id INTEGER, payment_type VARCHAR);
        INSERT INTO payment_types VALUES
            (0,'Flex Fare'),(1,'Credit card'),(2,'Cash'),(3,'No charge'),
            (4,'Dispute'),(5,'Unknown'),(6,'Voided trip');
    """)
    print("  ✓ payment_types  (7 rows)")

    con.close()

    size_mb = WAREHOUSE_PATH.stat().st_size / 1e6
    print(f"\nWarehouse ready: {WAREHOUSE_PATH}  ({size_mb:.1f} MB)")
    print("Next:  python chapters/01_first_call/run.py")


if __name__ == "__main__":
    main()
