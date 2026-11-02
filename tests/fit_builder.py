"""Écrit de petits fichiers FIT valides pour les tests (aucune donnée réelle dans le dépôt).

Format FIT : en-tête de 14 octets, messages de définition puis de données, CRC final.
Une valeur None est écrite comme « invalide » (valeur réservée du type de base).
"""
import struct
from datetime import UTC, datetime

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=UTC)

_CRC_TABLE = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
              0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]

# type de base FIT : (code, format struct, valeur invalide)
UINT8 = (0x02, "B", 0xFF)
UINT16 = (0x84, "H", 0xFFFF)
SINT32 = (0x85, "i", 0x7FFFFFFF)
UINT32 = (0x86, "I", 0xFFFFFFFF)
ENUM = (0x00, "B", 0xFF)

FILE_ID_FIELDS = [(0, ENUM), (1, UINT16), (2, UINT16), (4, UINT32)]  # type, manufacturer, product, time
# timestamp, lat, lon, distance, altitude, hr, speed, cadence
RECORD_FIELDS = [(253, UINT32), (0, SINT32), (1, SINT32), (5, UINT32), (2, UINT16),
                 (3, UINT8), (6, UINT16), (4, UINT8)]


def _crc(data: bytes, crc=0) -> int:
    for byte in data:
        tmp = _CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[byte & 0xF]
        tmp = _CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc


def _definition(local, global_num, fields) -> bytes:
    out = struct.pack("<BBBHB", 0x40 | local, 0, 0, global_num, len(fields))
    for num, (code, fmt, _) in fields:
        out += struct.pack("<BBB", num, struct.calcsize(fmt), code)
    return out


def _data(local, fields, values) -> bytes:
    out = struct.pack("<B", local)
    for (_, (_, fmt, invalid)), v in zip(fields, values, strict=True):
        out += struct.pack("<" + fmt, invalid if v is None else v)
    return out


def _fit_time(dt: datetime) -> int:
    return int((dt - FIT_EPOCH).total_seconds())


def _semicircles(deg):
    return None if deg is None else round(deg * 2**31 / 180)


def build_fit(points, garmin_product=3992, start=datetime(2026, 3, 1, 8, 0, tzinfo=UTC)) -> bytes:
    """points : dicts avec t (secondes depuis le départ) et facultativement
    lat, lon, distance_m, altitude_m, heart_rate, speed_mps, cadence."""
    body = _definition(0, 0, FILE_ID_FIELDS)
    body += _data(0, FILE_ID_FIELDS, [4, 1, garmin_product, _fit_time(start)])
    body += _definition(1, 20, RECORD_FIELDS)
    for p in points:
        alt = p.get("altitude_m")
        dist = p.get("distance_m")
        speed = p.get("speed_mps")
        body += _data(1, RECORD_FIELDS, [
            _fit_time(start) + p["t"],
            _semicircles(p.get("lat")), _semicircles(p.get("lon")),
            None if dist is None else round(dist * 100),
            None if alt is None else round((alt + 500) * 5),
            p.get("heart_rate"),
            None if speed is None else round(speed * 1000),
            p.get("cadence"),
        ])
    header = struct.pack("<BBHI4s", 14, 0x10, 2132, len(body), b".FIT")
    header += struct.pack("<H", _crc(header))
    data = header + body
    return data + struct.pack("<H", _crc(data))
