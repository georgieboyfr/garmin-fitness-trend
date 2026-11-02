"""
A lancer UNE SEULE FOIS, à la main, pour établir la session Garmin Connect
(gère le code MFA si activé) et générer le jeton mis en cache. Les
lancements suivants du service (synchro auto ou bouton "Lancer une
synchro") rechargent ce jeton automatiquement, sans interaction.

Se lance DANS le conteneur, pour être certain d'utiliser exactement la
même version de garminconnect/garth que le service au quotidien :

    docker compose run --rm garmin-fitness-trend python generate_token.py

`docker compose run` lance une instance jetable à part (le service
principal n'a pas besoin d'être arrêté), qui partage le même volume
./data que le conteneur qui tourne en continu.
"""
import os
import sys

from garminconnect import Garmin

from garmin_sync import _login_with_fallback

TOKEN_DIR = os.path.join(os.environ.get("DATA_DIR", "/data"), "garth_tokens")


def main():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")

    if not email or not password:
        print("GARMIN_EMAIL / GARMIN_PASSWORD non définis (voir .env).", file=sys.stderr)
        sys.exit(1)

    os.makedirs(TOKEN_DIR, exist_ok=True)
    client = Garmin(email, password, prompt_mfa=lambda: input("Code MFA Garmin : "))

    try:
        _login_with_fallback(client, TOKEN_DIR, prompt_mfa_for_fresh_login=lambda: input("Code MFA Garmin : "))
    except AssertionError as e:
        print(f"\nLe login a 'réussi' mais le profil Garmin renvoyé est invalide ({e}).")
        print("Vérifie que garminconnect/garth sont à jour dans backend/requirements.txt,")
        print("reconstruis l'image (`docker compose build`) puis réessaie.")
        sys.exit(1)

    print(f"Connexion réussie, jeton enregistré dans {TOKEN_DIR}")
    print("Le service peut maintenant se synchroniser sans interaction.")


if __name__ == "__main__":
    main()
