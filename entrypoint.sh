#!/bin/sh

echo "Starting Lizenzmanager with:"
echo "USERNAME: $USERNAME"
echo "BASE_DOMAIN: $BASE_DOMAIN"
echo "PORT: $PORT"

# Starte die Flask-Anwendung
exec python app.py
