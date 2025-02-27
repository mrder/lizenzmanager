# Verwende das vollständige Python 3 Image statt "slim"
FROM python:3

# Unbuffered stdout/stderr für besseres Logging
ENV PYTHONUNBUFFERED=1

# Wichtige Variablen als Umgebungsvariablen setzen
ENV USERNAME=admin
ENV PASSWORD=secret1991
ENV BASE_DOMAIN=http://localhost:5200
ENV UPLOAD_FOLDER=/app/uploads
ENV PORT=5200

WORKDIR /app

# Aktualisiere Systempakete und installiere Abhängigkeiten
RUN apt update && apt install -y \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Kopiere und installiere die Anforderungen
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den Anwendungscode
COPY . /app

# Setze Standardport (EXPOSE ist nur informativ)
EXPOSE 5200

# Starte die Flask-App mit den definierten Umgebungsvariablen
CMD ["sh", "-c", "python app.py"]
