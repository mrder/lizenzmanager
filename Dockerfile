# Verwende ein schlankes Python-Image als Basis
FROM python:3.9-slim

# Verhindere Pufferung der Python-Ausgaben (nützlich für Logs)
ENV PYTHONUNBUFFERED=1

# Setze das Arbeitsverzeichnis im Container
WORKDIR /app

# Kopiere die Abhängigkeitsliste und installiere die Pakete
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den Rest der Anwendung
COPY . .

# Setze Standard-Umgebungsvariablen (diese können später in Unraid überschrieben werden)
ENV USERNAME=admin
ENV PASSWORD=secret1991
ENV BASE_DOMAIN=http://localhost:5200
ENV UPLOAD_FOLDER=/app/uploads
ENV PORT=5200
ENV SECRET_KEY=a1s2d3f4g5h6j7k8l8ö9

# Exponiere den Port, den die App nutzt
EXPOSE 5200

# Starte die App
CMD ["python", "app.py"]
