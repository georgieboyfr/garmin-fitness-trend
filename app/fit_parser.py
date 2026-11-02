"""
Lecture d'un FIT d'activité : modèle de montre et séries temporelles des points.

Seuls les champs utiles aux calculs sont gardés : temps, distance, position,
altitude, FC, vitesse, cadence. Garmin écrit selon les montres `altitude` ou
`enhanced_altitude` (idem pour la vitesse) : la version « enhanced » est préférée.
L'origine de l'altitude (baromètre ou GPS) ne se lit pas dans le FIT : elle dépend
du modèle de montre (table devices).

Changer ce qui est extrait = incrémenter PARSER_VERSION : les séries sont relues.
"""
from dataclasses import dataclass

import fitdecode
import pyarrow as pa

PARSER_VERSION = 1

SEMICIRCLE_TO_DEG = 180.0 / 2**31

SCHEMA = pa.schema([
    ("timestamp", pa.timestamp("s", tz="UTC")),
    ("distance_m", pa.float64()),
    ("lat", pa.float64()),
    ("lon", pa.float64()),
    ("altitude_m", pa.float32()),
    ("heart_rate", pa.float32()),
    ("speed_mps", pa.float32()),
    ("cadence_rpm", pa.float32()),   # pas par minute d'une jambe (x2 pour les pas/min)
])


@dataclass
class FitData:
    garmin_product: int | None
    table: pa.Table

    @property
    def n_points(self) -> int:
        return self.table.num_rows

    def has(self, column) -> bool:
        return self.table.column(column).null_count < self.table.num_rows if self.n_points else False


def _first(frame, *names):
    for name in names:
        if frame.has_field(name):
            value = frame.get_value(name, fallback=None)
            if value is not None:
                return value
    return None


def _number(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # écarte NaN


def parse_fit(path) -> FitData:
    product = None
    cols = {name: [] for name in SCHEMA.names}
    with fitdecode.FitReader(str(path), check_crc=fitdecode.CrcCheck.DISABLED) as reader:
        for frame in reader:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name == "record":
                ts = frame.get_value("timestamp", fallback=None) if frame.has_field("timestamp") else None
                if ts is None:
                    continue
                lat = _number(_first(frame, "position_lat"))
                lon = _number(_first(frame, "position_long"))
                cols["timestamp"].append(ts)
                cols["distance_m"].append(_number(_first(frame, "distance")))
                cols["lat"].append(lat * SEMICIRCLE_TO_DEG if lat is not None and lon is not None else None)
                cols["lon"].append(lon * SEMICIRCLE_TO_DEG if lat is not None and lon is not None else None)
                cols["altitude_m"].append(_number(_first(frame, "enhanced_altitude", "altitude")))
                hr = _number(_first(frame, "heart_rate"))
                cols["heart_rate"].append(hr if hr else None)
                cols["speed_mps"].append(_number(_first(frame, "enhanced_speed", "speed")))
                cols["cadence_rpm"].append(_number(_first(frame, "cadence")))
            elif frame.name == "file_id" and product is None:
                # valeur brute : fitdecode traduit les modèles qu'il connaît en texte ("fr245")
                for name in ("garmin_product", "product"):
                    if frame.has_field(name):
                        raw = frame.get_field(name).raw_value
                        if isinstance(raw, int):
                            product = raw
                            break
    table = pa.table(cols, schema=SCHEMA)
    if table.num_rows:
        table = table.sort_by("timestamp")
    return FitData(garmin_product=product, table=table)
