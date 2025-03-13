# Verwende ein vollwertiges Python 3.11 Image
FROM python:3.11

# Verhindere Pufferung der Python-Ausgaben (nützlich für Logs)
ENV PYTHONUNBUFFERED=1

# Setze das Arbeitsverzeichnis im Container
WORKDIR /app

# Kopiere die Abhängigkeiten und installiere diese
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den restlichen Anwendungscode
COPY . .

# Setze Standard-Umgebungsvariablen (diese können via Docker-Compose oder im Container überschrieben werden)
ENV USERNAME=admin
ENV PASSWORD=admin
ENV BASE_DOMAIN=http://localhost:5200
ENV UPLOAD_FOLDER=/app/uploads
ENV PORT=5200
ENV SECRET_KEY=123456

# Exponiere den Port, auf dem die App läuft
EXPOSE 5200

# Verwende den entrypoint
ENTRYPOINT ["./entrypoint.sh"]
