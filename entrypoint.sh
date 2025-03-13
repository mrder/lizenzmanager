#!/bin/sh
echo "### Starte Lizenzmanager ###"
env | grep -E "USERNAME|PASSWORD|BASE_DOMAIN|UPLOAD_FOLDER|PORT|SECRET_KEY"

export USERNAME=${USERNAME:-admin}
export PASSWORD=${PASSWORD:-admin}
export BASE_DOMAIN=${BASE_DOMAIN:-http://localhost:5200}
export UPLOAD_FOLDER=${UPLOAD_FOLDER:-/app/uploads}
export PORT=${PORT:-5200}
export SECRET_KEY=${SECRET_KEY:-123456}

export FLASK_APP=app.py

# Falls noch kein Migrationsordner existiert, initialisiere die Migration
if [ ! -d "migrations" ]; then
    echo "Migrationsordner nicht gefunden. Führe Initialisierung und erste Migration durch..."
    flask db init
    flask db migrate -m "Initial migration"
fi

# Wende alle Migrationen an
echo "Führe 'flask db upgrade' aus..."
flask db upgrade

# Starte die Anwendung
exec python app.py
