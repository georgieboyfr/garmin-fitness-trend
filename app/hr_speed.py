"""
Forme du jour : la FC d'une sortie face à celle attendue à cette vitesse (fonctions pures).

1. Dans chaque sortie, portions stables d'une minute : vitesse ajustée à la pente (VAP) régulière
   pendant la minute et la minute et demie qui précède (la FC a eu le temps de se stabiliser),
   hors des 10 premières minutes (échauffement) et des récupérations qui suivent un effort plus
   rapide (la FC y reste haute plus longtemps). Le fractionné n'y entre que par ses portions
   stables (milieu des efforts longs, récupérations), le dénivelé par la VAP.
2. Relation FC = a + b × vitesse, apprise sur les portions des 90 jours précédant la sortie.
3. Écart moyen de la sortie à cette droite, en bpm : négatif = FC plus basse que d'habitude à
   la même vitesse (en forme), positif = plus haute (fatigue, chaleur, maladie, manque de sommeil).
"""
from bisect import bisect_left, bisect_right
from datetime import date, timedelta

import numpy as np

BLOCK_S = 60
SETTLE_S = 90              # la vitesse doit être stable aussi pendant les 90 s qui précèdent
WARMUP_S = 600
STEP_S = 20                # vitesse mesurée par tranches de 20 s (le GPS est trop bruité sur 10 s)
MAX_CV = 0.15              # variation de vitesse tolérée dans la minute
SETTLE_TOLERANCE = 0.15    # écart toléré entre la vitesse de la minute et celle des 90 s avant
RECOVERY_S = 180           # après un effort plus rapide, la FC reste haute plus longtemps
RECOVERY_TOLERANCE = 0.10  # les 3 min précédentes ne doivent pas être plus rapides de plus de 10 %
MIN_SPEED_MPS = 1.5        # en dessous : marche, la relation FC / vitesse change
MAX_HR_GAP_S = 10          # pas de FC interpolée sur un trou de plus de 10 s
HISTORY_DAYS = 90
MIN_HISTORY_BLOCKS = 60
MIN_ACTIVITY_BLOCKS = 5
SAME_THRESHOLD_BPM = 3.0


def steady_blocks(t, eq_distance, hr) -> list[tuple[float, float]]:
    """(vitesse ajustée en m/s, FC moyenne) de chaque minute stable de la sortie.
    eq_distance : distance équivalente sur le plat cumulée à chaque instant t."""
    t = np.asarray(t, dtype=float)
    eq = np.asarray(eq_distance, dtype=float)
    hr = np.asarray(hr, dtype=float)
    ok = np.isfinite(t) & np.isfinite(eq)
    t, eq, hr = t[ok], eq[ok], hr[ok]
    if t.size < 2 or t[-1] - t[0] < WARMUP_S + BLOCK_S:
        return []
    grid = np.arange(t[0], t[-1] + 1e-9, 1.0)
    dist = np.interp(grid, t, np.maximum.accumulate(eq))
    has_hr = np.isfinite(hr) & (hr > 0)
    if has_hr.sum() < 2:
        return []
    th, hv = t[has_hr], hr[has_hr]
    hr_grid = np.interp(grid, th, hv)
    # écart au relevé de FC le plus proche : pas de FC inventée dans un trou
    k = np.clip(np.searchsorted(th, grid), 1, th.size - 1)
    gap = np.minimum(np.abs(grid - th[k - 1]), np.abs(th[k] - grid))
    hr_grid[gap > MAX_HR_GAP_S] = np.nan

    steps = (dist[STEP_S::STEP_S] - dist[:-STEP_S:STEP_S]) / STEP_S     # vitesse par tranche de 10 s
    per_block = BLOCK_S // STEP_S
    recovery = RECOVERY_S // STEP_S
    settle = -(-SETTLE_S // STEP_S)          # arrondi au-dessus : au moins 90 s
    out = []
    first = WARMUP_S // STEP_S
    for s in range(max(first, settle), steps.size - per_block + 1, per_block):
        block = steps[s:s + per_block]
        v = block.mean()
        if v < MIN_SPEED_MPS or block.std() > MAX_CV * v:
            continue
        if np.abs(steps[s - settle:s] - v).max() > SETTLE_TOLERANCE * v:
            continue
        if steps[max(0, s - recovery):s].mean() > (1 + RECOVERY_TOLERANCE) * v:
            continue
        h = hr_grid[s * STEP_S:(s + per_block) * STEP_S]
        if np.isnan(h).any():
            continue
        out.append((round(float(v), 3), round(float(h.mean()), 1)))
    return out


def fit(blocks) -> dict | None:
    """Droite FC = a + b × vitesse (moindres carrés) sur les portions stables, ou None si elles sont
    trop peu nombreuses ou si la FC ne monte pas avec la vitesse."""
    if len(blocks) < MIN_HISTORY_BLOCKS:
        return None
    v = np.array([b[0] for b in blocks])
    h = np.array([b[1] for b in blocks])
    if np.ptp(v) < 0.3:
        return None
    b, a = np.polyfit(v, h, 1)
    if b <= 0:
        return None
    resid = h - (a + b * v)
    return {"a": float(a), "b": float(b), "n": len(blocks), "sd": float(resid.std()),
            "v_min": float(np.percentile(v, 5)), "v_max": float(np.percentile(v, 95))}


def assess(model, blocks) -> dict | None:
    """Écart de la sortie à la FC attendue : bpm (négatif = plus basse), équivalent en vitesse à FC
    égale (%), verdict. None sans modèle ou avec trop peu de portions comparables."""
    if not model:
        return None
    rows = [b for b in blocks if model["v_min"] <= b[0] <= model["v_max"]]
    if len(rows) < MIN_ACTIVITY_BLOCKS:
        return None
    v = np.array([r[0] for r in rows])
    h = np.array([r[1] for r in rows])
    diff = float((h - (model["a"] + model["b"] * v)).mean())
    speed_pct = float(-diff / model["b"] / v.mean() * 100)
    verdict = "same" if abs(diff) < SAME_THRESHOLD_BPM else ("better" if diff < 0 else "worse")
    return {"hr_diff": round(diff, 1), "speed_pct": round(speed_pct, 1), "verdict": verdict,
            "blocks": len(rows), "history_blocks": model["n"], "speed_mps": round(float(v.mean()), 2),
            "expected_hr": round(float(model["a"] + model["b"] * v.mean())), "hr": round(float(h.mean()))}


# ---------- tendance : vitesse à FC fixe au fil du temps (estimateur) ----------

TREND_HR_RATIO = 0.85      # FC de référence : 85 % de la LTHR (plage des sorties faciles, haut de Z1)
TREND_DAYS = 365           # droite FC / vitesse apprise sur les 12 mois qui se terminent ce jour-là


class SpeedTrend:
    """Vitesse à FC de référence (TREND_HR_RATIO × LTHR) au soir d'un jour donné, d'après les minutes
    stables (date, vitesse, FC) des TREND_DAYS jours précédents ; mise en cache par jour. Sert à
    ramener un effort passé à l'aérobie du jour : rapport des vitesses à FC égale entre les deux dates."""

    def __init__(self, blocks, lthr: float):
        self.hr = TREND_HR_RATIO * lthr
        rows = sorted((d[:10], v, h) for d, v, h in blocks)
        self.days = [r[0] for r in rows]
        self.blocks = [(r[1], r[2]) for r in rows]
        self._cache = {}

    def speed(self, day: date) -> float | None:
        if day not in self._cache:
            lo = bisect_left(self.days, (day - timedelta(days=TREND_DAYS - 1)).isoformat())
            hi = bisect_right(self.days, day.isoformat())
            m = fit(self.blocks[lo:hi])
            v = (self.hr - m["a"]) / m["b"] if m else None
            self._cache[day] = v if v and v > 0 else None
        return self._cache[day]

    def ratio(self, then: date, now: date) -> float:
        """Facteur de temps pour ramener un effort de `then` à l'aérobie de `now` : < 1 si tu cours
        plus vite à FC égale aujourd'hui ; 1 faute de données."""
        a, b = self.speed(then), self.speed(now)
        return a / b if a and b else 1.0

