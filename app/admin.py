"""
Routes de l'admin : session (connexion / déconnexion) et compte Garmin.

Les actions exigent la session de l'admin ET, hors GET, l'en-tête
X-Requested-With: admin-ui, qu'une page tierce ne peut pas envoyer (protection CSRF).
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from .auth import SESSION_COOKIE

log = logging.getLogger("admin")

STATIC_DIR = Path(__file__).parent / "static"
DISABLED = "Administration désactivée : définir ADMIN_PASSWORD_HASH dans .env (voir README)."


def require_admin(request: Request):
    auth = request.app.state.auth
    if not auth.enabled:
        raise HTTPException(403, DISABLED)
    if not auth.check_session(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(401, "Authentification requise")
    if request.method not in ("GET", "HEAD") and request.headers.get("x-requested-with") != "admin-ui":
        raise HTTPException(403, "En-tête X-Requested-With manquant")


pages = APIRouter(include_in_schema=False)
public = APIRouter(prefix="/admin/api")
protected = APIRouter(prefix="/admin/api", dependencies=[Depends(require_admin)])


@pages.get("/admin")
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html", headers={"Cache-Control": "no-cache"})


@pages.get("/admin/")
def admin_page_slash():
    return RedirectResponse("/admin")


# ---------- session ----------

class LoginBody(BaseModel):
    username: str
    password: str


@public.get("/session")
def session(request: Request):
    auth = request.app.state.auth
    return {"admin_enabled": auth.enabled,
            "authenticated": auth.check_session(request.cookies.get(SESSION_COOKIE))}


@public.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    auth, throttle = request.app.state.auth, request.app.state.login_throttle
    if not auth.enabled:
        raise HTTPException(403, DISABLED)
    client = request.client.host if request.client else "?"
    wait = throttle.retry_after(client)
    if wait:
        raise HTTPException(429, f"Trop d'essais : réessaie dans {wait // 60 + 1} min.",
                            headers={"Retry-After": str(wait)})
    if not auth.verify_password(body.username.strip(), body.password):
        throttle.failure(client)
        log.warning("Connexion admin refusée depuis %s", client)
        raise HTTPException(401, "Identifiant ou mot de passe incorrect")
    throttle.success(client)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(SESSION_COOKIE, auth.make_session(), max_age=auth.max_age, httponly=True,
                        samesite="strict", secure=secure, path="/admin")
    return {"authenticated": True}


@public.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/admin")
    return {"authenticated": False}


# ---------- compte Garmin ----------

class GarminLoginBody(BaseModel):
    email: str
    password: str
    remember: bool = False


class MfaBody(BaseModel):
    code: str


def _garmin_call(fn, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except Exception as e:
        name = e.__class__.__name__
        log.warning("Connexion Garmin refusée : %s: %s", name, e)
        status = 429 if "TooManyRequests" in name else 400
        raise HTTPException(status, f"Garmin a refusé la connexion : {e}") from None


@protected.get("/garmin")
def garmin_status(request: Request):
    return request.app.state.garmin_account.status()


@protected.post("/garmin/login")
def garmin_login(body: GarminLoginBody, request: Request):
    account = request.app.state.garmin_account
    _garmin_call(account.start_login, body.email.strip(), body.password, body.remember)
    return account.status()


@protected.post("/garmin/mfa")
def garmin_mfa(body: MfaBody, request: Request):
    account = request.app.state.garmin_account
    _garmin_call(account.submit_mfa, body.code)
    return account.status()


@protected.post("/garmin/mfa/cancel")
def garmin_mfa_cancel(request: Request):
    account = request.app.state.garmin_account
    account.cancel_login()
    return account.status()


@protected.post("/garmin/logout")
def garmin_logout(request: Request):
    account = request.app.state.garmin_account
    account.logout()
    return account.status()


@protected.post("/garmin/forget-password")
def garmin_forget_password(request: Request):
    account = request.app.state.garmin_account
    account.forget_password()
    return account.status()
