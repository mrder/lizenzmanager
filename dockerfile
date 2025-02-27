# Verwende ein vollwertiges Python 3.11 Image (anstatt das schlanke "slim" Image)
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

# Setze die globalen Umgebungsvariablen, die in der app.py verwendet werden
ENV USERNAME=admin
ENV PASSWORD=secret1991
ENV BASE_DOMAIN=http://localhost:5200
ENV UPLOAD_FOLDER=/app/uploads
ENV PORT=5200
ENV SECRET_KEY=a1s2d3f4g5h6j7k8l8ö9

# Exponiere den Port, auf dem die App läuft
EXPOSE 5200

# Starte die Anwendung
CMD ["python", "app.py"]
