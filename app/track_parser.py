"""
Lecture d'une trace d'activité quel que soit son format : FIT (Garmin) ou fichiers
de l'archive Strava (.fit, .gpx, éventuellement compressés en .gz).

Le résultat a toujours le schéma de fit_parser.SCHEMA ; un GPX n'a ni distance
(calculée ensuite depuis le GPS) ni vitesse.
"""
import gzip
import io
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pyarrow as pa

from .fit_parser import SCHEMA, FitData, parse_fit


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _float(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _time(text):
    if not text:
        return None
    dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def parse_gpx(data: bytes) -> FitData:
    cols = {name: [] for name in SCHEMA.names}
    for _, elem in ET.iterparse(io.BytesIO(data)):
        if _local(elem.tag) != "trkpt":
            continue
        values = {"hr": None, "cad": None, "ele": None, "time": None}
        for child in elem.iter():
            name = _local(child.tag)
            if name in values:
                values[name] = child.text
        ts = _time(values["time"])
        if ts is not None:
            hr = _float(values["hr"])
            cols["timestamp"].append(ts)
            cols["distance_m"].append(None)
            cols["lat"].append(_float(elem.get("lat")))
            cols["lon"].append(_float(elem.get("lon")))
            cols["altitude_m"].append(_float(values["ele"]))
            cols["heart_rate"].append(hr if hr else None)
            cols["speed_mps"].append(None)
            cols["cadence_rpm"].append(_float(values["cad"]))
        elem.clear()
    table = pa.table(cols, schema=SCHEMA)
    if table.num_rows:
        table = table.sort_by("timestamp")
    return FitData(garmin_product=None, table=table)


def parse_track(path) -> FitData:
    name = str(path).lower()
    if name.endswith(".gz"):
        with gzip.open(path, "rb") as f:
            data = f.read()
        name = name[:-3]
    else:
        data = None
    if name.endswith(".fit"):
        return parse_fit(path if data is None else io.BytesIO(data))
    if name.endswith(".gpx"):
        if data is None:
            with open(path, "rb") as f:
                data = f.read()
        return parse_gpx(data)
    raise ValueError(f"format de trace non pris en charge : {path}")
