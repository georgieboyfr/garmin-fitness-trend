"""Séries de points par activité, stockées en Parquet : series/<activity_id>.parquet.

Elles sont régénérables à tout moment depuis les FIT (voir processing.py).
"""
import os
from pathlib import Path

import pyarrow.parquet as pq


def series_path(series_dir, activity_id) -> Path:
    return Path(series_dir) / f"{activity_id}.parquet"


def write_series(series_dir, activity_id, table):
    path = series_path(series_dir, activity_id)
    tmp = path.with_name(path.name + ".part")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)
    return path


def read_series(series_dir, activity_id, columns=None):
    return pq.read_table(series_path(series_dir, activity_id), columns=columns)
