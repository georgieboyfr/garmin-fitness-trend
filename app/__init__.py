import os

# Version injectée au build de l'image (ARG APP_VERSION), affichée dans le pied de page et l'admin.
__version__ = os.environ.get("APP_VERSION") or "0.0.0-dev"
