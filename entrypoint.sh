#!/bin/sh

echo "### STARTE LIZENZMANAGER MIT DIESEN VARIABLEN ###"
env | grep -E "USERNAME|PASSWORD|BASE_DOMAIN|UPLOAD_FOLDER|PORT|SECRET_KEY"

export USERNAME=${USERNAME:-admin}
export PASSWORD=${PASSWORD:-admin}
export BASE_DOMAIN=${BASE_DOMAIN:-http://localhost:5200}
export UPLOAD_FOLDER=${UPLOAD_FOLDER:-/app/uploads}
export PORT=${PORT:-5200}
export SECRET_KEY=${SECRET_KEY:-123456}

# Setze FLASK_APP, damit Flask-Migrate funktioniert
export FLASK_APP=app.py

# Führe alle ausstehenden Migrationen aus
flask db upgrade

# Starte die Anwendung
exec python app.py
