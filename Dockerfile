# Verwende ein schlankes Python-Image als Basis
FROM python:3.9-slim

# Sorge dafür, dass Python-Ausgaben direkt im Log erscheinen
ENV PYTHONUNBUFFERED=1

# Setze das Arbeitsverzeichnis im Container
WORKDIR /app

# Kopiere die requirements.txt und installiere Abhängigkeiten
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den Rest der App in den Container
COPY . .

# Setze Standard-Umgebungsvariablen (diese können in Unraid überschrieben werden)
ENV USERNAME=admin
ENV PASSWORD=secret1991
ENV BASE_DOMAIN=http://localhost:5200
ENV UPLOAD_FOLDER=/app/uploads
ENV PORT=5200
ENV SECRET_KEY=a1s2d3f4g5h6j7k8l8ö9

# Exponiere den Port, auf dem die App läuft
EXPOSE 5200

# Starte die App
CMD ["python", "app.py"]
