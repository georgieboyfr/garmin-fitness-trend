"""
Tests de VMA (demi-Cooper) dans les sorties : détection (fonction pure), décisions de Greg (table
vma_tests), VMA la plus récente (saisie dans l'admin ou test confirmé).

Un test demi-Cooper se court 6 min le plus loin possible ; la VMA est la vitesse tenue, estimée par
le meilleur effort de 5 min de la sortie (comme la VMA de la page Forme). Une sortie est proposée :
- si son nom ou sa description parle de test, de VMA ou de Cooper ;
- ou si son meilleur effort de 5 min atteint au moins 97 % du meilleur de l'année précédente, dans
  une sortie de moins de 75 min qui n'est pas une course confirmée (une séance courte et à fond).
Seules les sorties route des 6 derniers mois sont proposées : au-delà, une VMA ne sert plus de
référence.
"""
import re
from datetime import UTC, date, datetime, timedelta

KEYWORDS = ("cooper", "vma", "test")
NEAR_BEST = 0.97               # 5 min à au moins 97 % du meilleur 5 min de l'année précédente
BEST_DAYS = 365
MAX_MOVING_S = 75 * 60         # une séance de test est courte
PROPOSE_DAYS = 182             # proposées sur les 6 derniers mois
EFFORT_S = 300                 # meilleur effort de 5 min (efforts de durée enregistrés)


def five_minute_speeds(efforts) -> dict[int, float]:
    """Vitesse (m/s) du meilleur effort route de 5 min de chaque sortie."""
    return {e["id"]: e["value"] / EFFORT_S for e in efforts
            if e.get("terrain") == "road" and e["kind"] == "duration" and e["key"] == EFFORT_S
            and e.get("id")}


def candidates(acts, efforts, race_ids, today: date) -> list[dict]:
    """Sorties qui ressemblent à un test de VMA, avec la VMA qu'elles donnent et leurs raisons."""
    v5 = five_minute_speeds(efforts)
    road = sorted((a for a in acts if a.get("terrain") == "road" and a["id"] in v5), key=lambda a: a["start"])
    out = []
    for a in road:
        day = a["start"].date()
        if day < today - timedelta(days=PROPOSE_DAYS) or a["id"] in race_ids:
            continue
        reasons = []
        text = f"{a.get('name') or ''} {a.get('description') or ''}".lower()
        word = next((k for k in KEYWORDS if re.search(rf"\b{k}", text)), None)
        if word:
            reasons.append(f"mot-clé « {word} »")
        before = [v5[b["id"]] for b in road
                  if day - timedelta(days=BEST_DAYS) <= b["start"].date() < day and b["id"] != a["id"]]
        best = max(before, default=0.0)
        near = best > 0 and v5[a["id"]] >= NEAR_BEST * best
        short = (a.get("moving_duration_s") or 0) <= MAX_MOVING_S
        if near and short:
            reasons.append(f"5 min à {v5[a['id']] * 3.6:.1f} km/h, {v5[a['id']] / best * 100:.0f} % de ton "
                           "meilleur 5 min de l'année, sortie courte")
        if word or (near and short):
            out.append({"id": a["id"], "vma_kmh": round(v5[a["id"]] * 3.6, 1), "reasons": reasons})
    return out


def decisions(conn) -> dict[int, str]:
    return dict(conn.execute("SELECT activity_id, status FROM vma_tests").fetchall())


def decide(conn, activity_id: int, status: str | None):
    """Confirme ou rejette un test ; None efface la décision (la sortie redevient candidate)."""
    with conn:
        if status is None:
            conn.execute("DELETE FROM vma_tests WHERE activity_id=?", (activity_id,))
            return
        if status not in ("confirmed", "rejected"):
            raise ValueError("statut attendu : confirmed ou rejected")
        if not conn.execute("SELECT 1 FROM activities WHERE id=?", (activity_id,)).fetchone():
            raise ValueError("sortie inconnue")
        conn.execute(
            "INSERT INTO vma_tests (activity_id, status, decided_at) VALUES (?, ?, ?)"
            " ON CONFLICT(activity_id) DO UPDATE SET status=excluded.status, decided_at=excluded.decided_at",
            (activity_id, status, datetime.now(UTC).replace(microsecond=0).isoformat()))


def confirmed_vmas(acts, efforts, conn) -> list[dict]:
    """VMA des tests confirmés : {date, kmh, activity_id, name}."""
    v5 = five_minute_speeds(efforts)
    by_id = {a["id"]: a for a in acts}
    out = []
    for i, st in decisions(conn).items():
        if st == "confirmed" and i in v5 and i in by_id:
            a = by_id[i]
            out.append({"date": a["start"].date().isoformat(), "kmh": round(v5[i] * 3.6, 1), "activity_id": i,
                        "name": a.get("name") or "Test VMA"})
    return sorted(out, key=lambda v: v["date"])


def all_vmas(acts, efforts, conn, training: dict) -> list[dict]:
    """Toutes les VMA datées : tests confirmés et VMA saisie dans l'admin, de la plus ancienne à la
    plus récente."""
    out = confirmed_vmas(acts, efforts, conn)
    if training.get("vma_kmh") and training.get("vma_date"):
        out.append({"date": training["vma_date"], "kmh": training["vma_kmh"], "activity_id": None,
                    "name": "VMA testée (admin)"})
    return sorted(out, key=lambda v: v["date"])


def latest(vmas: list[dict], today: date | None = None) -> dict | None:
    """La VMA la plus récente (jusqu'à `today`)."""
    rows = [v for v in vmas if today is None or v["date"] <= today.isoformat()]
    return rows[-1] if rows else None
