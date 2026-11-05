"""
Coach sur les données du moment : chargement (sorties, calendrier, disponibilités, habitudes),
plan d'une semaine donnée, bilan du dimanche et réajustement de la semaine suivante. Partagé par
la page Coach et le planificateur (notification du dimanche soir).

- La semaine en cours est celle du plan calculé son lundi (forme et estimation de la veille) : elle
  ne bouge pas au fil des sorties ; le réajustement tiré du bilan de la semaine d'avant s'y applique.
- Le bilan d'une semaine est recalculé tant qu'elle n'est pas close, puis figé en base : le lundi
  une fois la synchro du jour faite, sinon le mardi (les sorties du dimanche sont alors arrivées).
- Bilans imbriqués : le plan d'une semaine dépend du bilan de la précédente ; au-delà d'un niveau,
  seuls les bilans figés et les réponses servent (pas de calcul en cascade).
- Temps prévu de chaque échéance, chaque semaine (étape 5) : l'estimateur avec la forme du dimanche
  soir, projeté sur la fitness que le plan du lundi donne le matin de la course, et enregistré ; à
  l'ajout d'une course, les semaines depuis le départ du plan sont rejouées (12 au plus).
"""
import math
from datetime import date, timedelta

from . import (
    coach,
    coach_plan,
    coach_review,
    coach_week,
    coach_workouts,
    estimator,
    metrics_job,
    physio,
    queries,
    settings,
    stats,
    tracked,
)

PREDICTION_VERSION = f"{tracked.VERSION}-plan{coach_plan.PLAN_VERSION}"
REPLAY_WEEKS = 12


class Coach:
    def __init__(self, cfg, conn, today: date, dem=None, synced_today: bool = False):
        self.cfg, self.today, self.dem, self.synced_today = cfg, today, dem, synced_today
        self.data = tracked.load_data(cfg, conn)
        self.races = coach.all_races(conn)
        self.profile = settings.get(conn, "coach")
        self.factors = tracked.corrections(conn)
        self.tracked_races = tracked.all_races(conn)
        tracks = queries.track_signatures(conn)
        self.lthr_est = metrics_job.lthr_estimate(conn, today)
        params = metrics_job.params_of(cfg, conn)
        self.hr_max = params["hr_max"]
        self.training = settings.get(conn, "training")
        lthr = self.data.get("lthr")
        self.hr = {"hr_max": self.hr_max, "hr_rest": params["hr_rest"],
                   "easy_hr": coach_workouts.easy_hr(self.training["easy_hr_method"], self.hr_max,
                                                     params["hr_rest"], lthr)}
        self.reviews = coach_review.all_reviews(conn)
        self.choices = coach.choices(conn)
        self.cal = coach.calendar(self.races, today)
        self.inferred = coach.availability_from_history(self.data["acts"], today)
        self.habits = coach.effective_habits(self.profile["habits"],
                                             coach.habits_from_history(self.data["acts"], tracks, today))
        self.availability = coach.effective_availability(self.profile["availability"], self.inferred)
        self._weeks: dict[str, dict | None] = {}
        self._summaries: dict[str, dict] = {}
        self._slopes: dict[date, dict] = {}

    # ---------- plan ----------

    def physio(self, day: date) -> dict:
        """Repères physiologiques du jour (VMA testée de l'admin prioritaire), avec la FC du coureur."""
        out = physio.physiology(self.data["efforts"], day, self.lthr_est, self.hr_max, self.data["trend"],
                                self.training.get("vma_kmh"))
        return {**out, "hr": self.hr}

    def optional_done(self) -> dict[int, list[str]]:
        """Sorties optionnelles faites, lues dans les bilans des semaines (figés ou calculés) :
        {jour de la semaine : lundis des semaines où celle de ce jour a été faite}."""
        out: dict[int, list[str]] = {}
        summaries = {m: r.get("summary") for m, r in self.reviews.items()} | self._summaries
        for monday_, summary in summaries.items():
            for wd in (summary or {}).get("optional_done") or ():
                out.setdefault(wd, []).append(monday_)
        return out

    def main_on(self, day: date) -> dict | None:
        """Course principale vue de ce jour-là."""
        return coach.calendar(self.races, day)["main"]

    def plan_on(self, day: date, main: dict | None = None, adjust=()) -> dict | None:
        """Plan vers la course principale vue de ce jour-là ; sans course à venir, maintien de forme."""
        main = main or self.main_on(day)
        cal = coach.calendar(self.races, day)
        physio_now = self.physio(day)
        if not main:
            return coach_plan.apply_choices(self.maintenance_on(day, cal, physio_now, adjust), self.choices)
        others = [r for r in cal["upcoming"] if r["id"] != main["id"]] + [
            r for r in cal["past"]
            if (day - date.fromisoformat(r["race_date"])).days <= coach_plan.RECOVERY_LOOKBACK_DAYS]
        options = {"ramp_pct": self.profile["ramp_pct"], "long_extension": self.profile["long_extension"],
                   "periods": self.profile["periods"], "start": coach.plan_start(main, cal["past"]),
                   "nuance": self.profile.get("nuance"), "optional_done": self.optional_done(),
                   "adjust": [a for a in adjust if a]}
        plan = coach.plan_for(self.cfg, main, day, self.data, self.availability,
                              self.profile["max_sessions"], self.habits, physio_now, options, others)
        return coach_plan.apply_choices(plan, self.choices)

    def maintenance_on(self, day: date, cal: dict, physio_now: dict, adjust=()) -> dict:
        """Maintien de forme sans course à venir : récupération de la dernière course d'abord,
        cycle compté depuis son lendemain."""
        recent = [r for r in cal["past"]
                  if (day - date.fromisoformat(r["race_date"])).days <= coach_plan.RECOVERY_LOOKBACK_DAYS]
        options = {"ramp_pct": self.profile["ramp_pct"], "periods": self.profile["periods"],
                   "start": coach.maintenance_start(cal["past"]), "adjust": [a for a in adjust if a],
                   "optional_done": self.optional_done(),
                   "orientation": self.profile.get("orientation")}
        return coach.maintenance_for(self.cfg, day, self.data, self.availability,
                                     self.profile["max_sessions"], self.habits, physio_now, options, recent)

    def library(self) -> list[dict]:
        """Bibliothèque de séances avec les allures, la FC et la vitesse de montée du coureur."""
        physio_now = self.physio(self.today)
        rates = coach_plan.load_rates(self.data["acts"], self.today)
        paces = {**coach._paces(physio_now), "lthr": self.data.get("lthr"), "easy": rates["easy_pace"],
                 "easy_vam": rates["easy_vam"], "race": None}
        return coach_workouts.library(paces, rates)

    def week_plan(self, monday_: date, depth: int = 0) -> dict | None:
        """Plan calculé le lundi d'une semaine (proposition d'objectif de la veille), réajustement
        tiré du bilan de la semaine d'avant compris."""
        iso = monday_.isoformat()
        if iso in self._weeks and depth == 0:
            return self._weeks[iso]
        main = self.main_on(monday_)
        if main and not main.get("target_s"):
            main = {**main, "proposal": coach.proposed_target(
                self.cfg, main, monday_ - timedelta(days=1), self.data, self.factors, self.dem)}
        plan = self.plan_on(monday_, main, [self.adjust_for(monday_, depth)])
        if depth == 0:
            self._weeks[iso] = plan
        return plan

    def week_view(self, monday_: date, plan: dict | None = None) -> dict | None:
        plan = plan or self.week_plan(monday_)
        if not plan or not plan["weeks"] or plan["weeks"][0]["monday"] != monday_.isoformat():
            return None
        upto = min(self.today, coach_review.sunday(monday_))
        return coach_week.week_view(plan["weeks"][0], self.data["acts"], upto, self.data["confirmed"])

    def freshness(self, day: date) -> dict | None:
        """Fraîcheur au matin d'un jour (forme de la page Forme : fitness − fatigue de la veille),
        en % de la fitness, avec la zone du jour J du plan (mêmes seuils que la page Forme)."""
        daily = {d: v for d, v in estimator._daily_load(self.data["acts"]).items() if d < day}
        if not daily:
            return None
        last = stats.banister(daily, min(daily), day)[-1]
        fitness, form = last["fitness"], last["form"]
        pct = form / fitness * 100 if fitness > 0 else 0.0
        zone, label = coach_plan._race_form(pct)
        return {"fitness": round(fitness, 1), "form": round(form, 1), "pct": round(pct),
                "zone": zone, "label": label}

    def period_effects(self) -> dict[int, dict]:
        """Effet de chaque période particulière à venir (index dans le profil) : plan recalculé sans
        elle, écart de fitness le jour J de la course principale et de temps prévu (relation
        personnelle entre fitness et niveau) ; sans course, écart de fitness au bout des semaines
        du maintien."""
        periods = self.profile["periods"] or []
        future = [i for i, p in enumerate(periods) if p["end"] >= self.today.isoformat()]
        if not future:
            return {}
        main = self.main_on(self.today)
        estimate = None
        if main:
            estimate = coach.proposed_target(self.cfg, main, self.today, self.data, self.factors, self.dem)
            if not main.get("target_s") and estimate:
                main = {**main, "proposal": estimate}

        def fitness_of(plan):
            if not plan:
                return None
            return coach.race_fitness_in_plan(plan, main) if main else plan.get("end_fitness")
        with_all = fitness_of(self.plan_on(self.today, main))
        saved, out = self.profile, {}
        slope = self.slope(self.today)["value"]
        try:
            for i in future:
                self.profile = {**saved, "periods": [p for j, p in enumerate(periods) if j != i] or None}
                without = fitness_of(self.plan_on(self.today, main))
                if with_all is None or without is None:
                    continue
                delta = with_all - without
                row = {"fitness_delta": round(delta, 1), "race": main["name"] if main else None}
                if estimate:
                    row["time_delta_s"] = round(estimate["realistic_s"] * (math.exp(slope * delta) - 1))
                out[i] = row
        finally:
            self.profile = saved
        return out

    # ---------- temps prévu le jour J ----------

    def slope(self, day: date) -> dict:
        if day not in self._slopes:
            self._slopes[day] = estimator.fitness_slope(self.data["acts"], self.data["efforts"], day)
        return self._slopes[day]

    def prediction(self, race: dict, monday_: date) -> dict | None:
        """Temps prévu le jour J vu du lundi d'une semaine : l'estimateur avec la forme du dimanche
        soir (correction de l'admin comprise), projeté sur la fitness du plan le matin de la course."""
        form_day = monday_ - timedelta(days=1)
        estimate = coach.proposed_target(self.cfg, race, form_day, self.data, self.factors, self.dem)
        if not estimate:
            return None
        fitness_now = tracked.fitness_on(self.data["acts"], form_day)
        fitness_race = coach.race_fitness_in_plan(self.week_plan(monday_), race)
        slope = self.slope(form_day)["value"]
        p = coach.projected(estimate, fitness_now, fitness_race, slope)
        return {"week": monday_.isoformat(), "form_day": form_day.isoformat(),
                "current_s": estimate["realistic_s"], **p,
                "fitness_now": round(fitness_now, 1) if fitness_now is not None else None,
                "fitness_race": round(fitness_race, 1) if fitness_race is not None else None,
                "slope": slope}

    def record_predictions(self, conn) -> int:
        """Temps prévus manquants des échéances à venir : la semaine en cours une fois la semaine
        d'avant close (sorties du dimanche arrivées), et les semaines depuis l'ajout de la course
        (REPLAY_WEEKS au plus), rejouées. Retourne le nombre enregistré."""
        monday_ = coach_plan.monday(self.today)
        done = 0
        for race in self.cal["upcoming"]:
            have = {p["week"] for p in coach.predictions(conn, race["id"])}
            added = date.fromisoformat((race.get("created_at") or race["race_date"])[:10])
            created = coach_plan.monday(added)
            first = max(created, monday_ - timedelta(weeks=REPLAY_WEEKS - 1))
            w = first
            while w <= monday_:
                live = w == monday_
                if (w.isoformat() not in have and w.isoformat() <= race["race_date"]
                        and (not live or self.closed(w - timedelta(days=7)))):
                    p = self.prediction(race, w)
                    if p:
                        coach.save_prediction(conn, race["id"], p, not live, PREDICTION_VERSION)
                        done += 1
                w += timedelta(days=7)
        return done

    # ---------- bilan ----------

    def reviewable(self, monday_: date) -> bool:
        """Une semaine se passe en revue à partir de son dimanche, si le plan existait déjà
        (course principale ajoutée au plus tard ce dimanche)."""
        sunday = coach_review.sunday(monday_)
        main = self.main_on(monday_)
        if sunday > self.today:
            return False
        if not main:
            return True                      # maintien de forme : chaque semaine se passe en revue
        past = coach.calendar(self.races, monday_)["past"]
        return coach.plan_start(main, past) <= sunday

    def closed(self, monday_: date) -> bool:
        """Semaine close : bilan figé (les sorties du dimanche sont arrivées)."""
        next_monday = monday_ + timedelta(days=7)
        return self.today > next_monday or (self.today == next_monday and self.synced_today)

    def answers(self, monday_: date) -> dict:
        row = self.reviews.get(monday_.isoformat()) or {}
        return {"next_week": row.get("next_week"), "feeling": row.get("feeling"),
                "answered": bool(row.get("answered_at"))}

    def review(self, monday_: date, conn=None, depth: int = 0) -> dict | None:
        """Bilan d'une semaine : figé s'il l'est, sinon calculé (et figé si la semaine est close)."""
        if not self.reviewable(monday_):
            return None
        row = self.reviews.get(monday_.isoformat()) or {}
        if row.get("summary"):
            return row["summary"]
        summary = self._summaries.get(monday_.isoformat())
        if summary is None and depth <= 1:
            summary = self._compute_review(monday_, depth)
        if summary is not None and conn is not None and self.closed(monday_):
            coach_review.save_summary(conn, monday_, summary)
            self.reviews.setdefault(monday_.isoformat(), {"monday": monday_.isoformat()})["summary"] = summary
        return summary

    def _compute_review(self, monday_: date, depth: int) -> dict | None:
        plan = self.week_plan(monday_, depth)
        week = self.week_view(monday_, plan) if plan else None
        if not week:
            return None
        sunday = coach_review.sunday(monday_)
        state = coach_plan.fitness_state(self.data["acts"], monday_ + timedelta(days=7))
        races = []
        for r in coach.calendar(self.races, sunday)["upcoming"]:
            before = coach.proposed_target(self.cfg, r, monday_ - timedelta(days=1), self.data,
                                           self.factors, self.dem)
            after = coach.proposed_target(self.cfg, r, sunday, self.data, self.factors, self.dem)
            races.append({**r, "before_s": before and before["realistic_s"],
                          "after_s": after and after["realistic_s"]})
        summary = coach_review.review(week, plan, state, races)
        self._summaries[monday_.isoformat()] = summary
        return summary

    def adjust_for(self, monday_: date, depth: int = 0) -> dict | None:
        """Réajustement d'une semaine, tiré du bilan de la précédente et des réponses du coureur."""
        prev = monday_ - timedelta(days=7)
        summary = self.review(prev, None, depth + 1)
        answers = self.answers(prev)
        return coach_review.adjustment(answers, summary)
