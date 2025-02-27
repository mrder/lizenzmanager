#!/bin/sh

# Debugging: Zeige die Umgebungsvariablen beim Start
echo "### STARTE LIZENZMANAGER MIT FOLGENDEN EINSTELLUNGEN ###"
env | grep -E "USERNAME|PASSWORD|BASE_DOMAIN|UPLOAD_FOLDER|PORT"

# Falls eine Variable fehlt, Standardwerte setzen
export USERNAME=${USERNAME:-admin}
export PASSWORD=${PASSWORD:-secret1991}
export BASE_DOMAIN=${BASE_DOMAIN:-http://localhost:5200}
export UPLOAD_FOLDER=${UPLOAD_FOLDER:-/app/uploads}
export PORT=${PORT:-5200}

# Starte die Anwendung
exec python app.py
