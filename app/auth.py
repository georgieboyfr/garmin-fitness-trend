"""
Authentification de l'admin.

- Identifiant et mot de passe hashé (argon2) fournis par l'environnement :
  ADMIN_USER et ADMIN_PASSWORD_HASH. Pour générer le hash :

      docker compose run --rm garmin-fitness-trend python -m app.auth

- Session : cookie HttpOnly signé (HMAC) contenant sa date d'expiration. La signature
  dépend du hash du mot de passe : changer le mot de passe ferme toutes les sessions.
- Tentatives de connexion limitées (5 échecs par quart d'heure et par adresse).
  Derrière le reverse proxy du Synology, toutes les requêtes viennent de la même
  adresse : la limite devient alors globale, ce qui convient à un usage personnel.
"""
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

SESSION_COOKIE = "gft_admin"
SESSION_MAX_AGE = 30 * 24 * 3600

_hasher = PasswordHasher()
# hash factice vérifié quand l'identifiant est faux : la réponse prend le même temps
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def load_or_create_secret(path) -> bytes:
    """Clé de signature des sessions, créée au premier démarrage sur le volume de données."""
    path = Path(path)
    try:
        return bytes.fromhex(path.read_text(encoding="ascii").strip())
    except FileNotFoundError:
        pass
    key = secrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(key.hex())
    return key


class AdminAuth:
    def __init__(self, username, password_hash, secret: bytes, max_age=SESSION_MAX_AGE, clock=time.time):
        self.username = username or ""
        self.password_hash = password_hash or ""
        self.secret = secret
        self.max_age = max_age
        self.clock = clock

    @property
    def enabled(self) -> bool:
        return bool(self.username and self.password_hash)

    def verify_password(self, username: str, password: str) -> bool:
        if not self.enabled:
            return False
        user_ok = secrets.compare_digest(username.encode(), self.username.encode())
        try:
            pw_ok = _hasher.verify(self.password_hash if user_ok else _DUMMY_HASH, password)
        except (VerificationError, InvalidHashError):
            pw_ok = False
        return user_ok and pw_ok

    def _sign(self, expires: int) -> str:
        msg = f"{self.username}|{expires}|{self.password_hash}".encode()
        return hmac.new(self.secret, msg, hashlib.sha256).hexdigest()

    def make_session(self) -> str:
        expires = int(self.clock()) + self.max_age
        return f"{expires}.{self._sign(expires)}"

    def check_session(self, value: str | None) -> bool:
        if not self.enabled or not value:
            return False
        expires, _, sig = value.partition(".")
        if not expires.isdigit() or int(expires) < self.clock():
            return False
        return secrets.compare_digest(sig.encode(), self._sign(int(expires)).encode())


class LoginThrottle:
    """Bloque une adresse après max_failures échecs dans la fenêtre glissante."""

    def __init__(self, max_failures=5, window_s=15 * 60, clock=time.monotonic):
        self.max_failures = max_failures
        self.window_s = window_s
        self.clock = clock
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key):
        now = self.clock()
        recent = [t for t in self._failures.get(key, []) if now - t < self.window_s]
        self._failures[key] = recent
        return recent

    def retry_after(self, key) -> int:
        """Secondes à attendre avant un nouvel essai (0 si autorisé)."""
        recent = self._recent(key)
        if len(recent) < self.max_failures:
            return 0
        return max(1, int(recent[0] + self.window_s - self.clock()) + 1)

    def failure(self, key):
        self._recent(key).append(self.clock())

    def success(self, key):
        self._failures.pop(key, None)


def main():
    from getpass import getpass

    password = getpass("Mot de passe de l'admin : ")
    if len(password) < 10:
        raise SystemExit("Au moins 10 caractères.")
    if getpass("Confirmation : ") != password:
        raise SystemExit("Les deux saisies diffèrent.")
    # guillemets simples : docker compose n'interprète pas les $ du hash
    print(f"\nÀ copier dans .env :\nADMIN_PASSWORD_HASH='{hash_password(password)}'")


if __name__ == "__main__":
    main()
