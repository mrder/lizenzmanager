#!/bin/sh
echo "### Starte Lizenzmanager mit folgenden Variablen ###"
env | grep -E "USERNAME|PASSWORD|BASE_DOMAIN|UPLOAD_FOLDER|PORT|SECRET_KEY|DATABASE_URI"

export USERNAME=${USERNAME:-admin}
export PASSWORD=${PASSWORD:-admin}
export BASE_DOMAIN=${BASE_DOMAIN:-http://localhost:5200}
export UPLOAD_FOLDER=${UPLOAD_FOLDER:-/app/uploads}
export PORT=${PORT:-5200}
export SECRET_KEY=${SECRET_KEY:-123456}
export DATABASE_URI=${DATABASE_URI:-sqlite:////data/licenses.db}
export FLASK_APP=app.py

# Falls der Migrationsordner noch nicht existiert, initialisiere die Migration
if [ ! -d "migrations" ]; then
    echo "Migrationsordner nicht gefunden. Initialisiere Migration..."
    flask db init
    flask db migrate -m "Initial migration"
fi

echo "Führe 'flask db upgrade' aus..."
flask db upgrade

exec python app.py
