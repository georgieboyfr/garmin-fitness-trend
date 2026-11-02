from datetime import UTC, datetime

import fitdecode
import pytest

from app.fit_parser import parse_fit

from .fit_builder import build_fit

START = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)


def write(tmp_path, points, **kw):
    path = tmp_path / "a.fit"
    path.write_bytes(build_fit(points, start=START, **kw))
    return path


def test_full_record(tmp_path):
    pts = [
        {"t": 0, "lat": 45.1885, "lon": 5.7245, "distance_m": 0.0, "altitude_m": 212.4,
         "heart_rate": 120, "speed_mps": 2.5, "cadence": 85},
        {"t": 5, "lat": 45.1886, "lon": 5.7246, "distance_m": 12.5, "altitude_m": 213.0,
         "heart_rate": 125, "speed_mps": 2.6, "cadence": 86},
    ]
    data = parse_fit(write(tmp_path, pts, garmin_product=3076))
    assert data.garmin_product == 3076
    assert data.n_points == 2
    row = data.table.to_pylist()[1]
    assert row["timestamp"] == datetime(2026, 3, 1, 8, 0, 5, tzinfo=UTC)
    assert row["lat"] == pytest.approx(45.1886, abs=1e-6)
    assert row["lon"] == pytest.approx(5.7246, abs=1e-6)
    assert row["distance_m"] == pytest.approx(12.5)
    assert row["altitude_m"] == pytest.approx(213.0)
    assert row["heart_rate"] == 125 and row["cadence_rpm"] == 86
    assert row["speed_mps"] == pytest.approx(2.6)
    assert data.has("lat") and data.has("altitude_m") and data.has("heart_rate")


def test_forerunner_35_without_altitude_and_treadmill_without_gps(tmp_path):
    # Forerunner 35 : pas d'altitude ; tapis : pas de GPS
    pts = [{"t": i, "distance_m": i * 3.0, "heart_rate": 140} for i in range(10)]
    data = parse_fit(write(tmp_path, pts, garmin_product=2503))
    assert data.garmin_product == 2503
    assert not data.has("lat") and not data.has("altitude_m")
    assert data.has("heart_rate")
    assert data.table.column("lat").null_count == 10


def test_records_sorted_and_zero_hr_dropped(tmp_path):
    pts = [{"t": 10, "heart_rate": 0}, {"t": 0, "heart_rate": 130}, {"t": 5}]
    data = parse_fit(write(tmp_path, pts))
    rows = data.table.to_pylist()
    assert [r["timestamp"].second for r in rows] == [0, 5, 10]
    assert [r["heart_rate"] for r in rows] == [130, None, None]


def test_empty_activity(tmp_path):
    data = parse_fit(write(tmp_path, []))
    assert data.n_points == 0 and not data.has("lat")


def test_corrupt_file_raises(tmp_path):
    path = tmp_path / "bad.fit"
    path.write_bytes(b"\x0e\x10\x00\x00\x00\x00\x00\x00.FIT" + b"\x00" * 3)
    with pytest.raises(fitdecode.FitError):
        parse_fit(path)
