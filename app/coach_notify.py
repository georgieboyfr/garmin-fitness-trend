"""
Notification du bilan du dimanche soir (phase 4, étape 4), par ntfy : une seule par semaine, et
c'est tout (section 6 du brief). L'adresse du sujet ntfy et son jeton éventuel sont dans le .env
(NTFY_URL, NTFY_TOKEN) ; l'heure et l'adresse publique du lien se règlent dans l'admin.

Aucun nom ni description venus de Strava dans le message : seulement le verdict et les chiffres.
"""
import logging
import urllib.parse
import urllib.request
from datetime import date

from . import coach_plan

log = logging.getLogger("coach_notify")
TIMEOUT_S = 15


class NotifyError(RuntimeError):
    pass


def send(cfg, title: str, message: str, click: str | None = None, tags: str | None = None):
    """Envoie une notification ntfy (titre et lien en paramètres d'adresse, pour l'UTF-8)."""
    if not cfg.ntfy_url:
        raise NotifyError("NTFY_URL n'est pas renseignée dans le .env.")
    params = {"title": title}
    if click:
        params["click"] = click
    if tags:
        params["tags"] = tags
    url = cfg.ntfy_url + ("&" if "?" in cfg.ntfy_url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=message.encode("utf-8"), method="POST")
    if cfg.ntfy_token:
        req.add_header("Authorization", f"Bearer {cfg.ntfy_token}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            if r.status >= 300:
                raise NotifyError(f"ntfy a répondu {r.status}.")
    except OSError as e:
        raise NotifyError(f"Envoi impossible : {e}") from None


def review_message(summary: dict) -> tuple[str, str]:
    """Titre et texte de la notification : verdict, séances, charge, puis l'invitation à répondre."""
    v, planned, done = summary["verdict"], summary["planned"], summary["done"]
    text = (f"{done['sessions']} séance{'s' if done['sessions'] > 1 else ''} sur {planned['sessions']}, "
            f"charge {done['load']} pour {planned['load']} prévue. "
            "Comment s'annonce la semaine prochaine, et comment te sens-tu ?")
    return f"Bilan : {v['label'].lower()}", text


def is_due(now_local, cfg: dict, last_week: str | None) -> bool:
    """Le dimanche, à partir de l'heure réglée, une fois par semaine."""
    return (cfg["review_enabled"] and now_local.weekday() == 6 and now_local.hour >= cfg["review_hour"]
            and last_week != coach_plan.monday(now_local.date()).isoformat())


def review_link(cfg_notif: dict) -> str | None:
    base = cfg_notif.get("public_url")
    return f"{base}/coach?vue=semaine#bilan" if base else None


def notify_review(cfg, coach_ctx, today: date, cfg_notif: dict) -> bool:
    """Bilan de la semaine en cours (dimanche) envoyé par ntfy. False s'il n'y a rien à dire."""
    summary = coach_ctx.review(coach_plan.monday(today))
    if not summary:
        return False
    title, text = review_message(summary)
    send(cfg, title, text, review_link(cfg_notif), tags="running")
    log.info("Bilan du dimanche envoyé par ntfy")
    return True
