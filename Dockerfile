FROM python:3.9-slim

# Unbuffered stdout/stderr
ENV PYTHONUNBUFFERED=1

# Standard-Umgebungsvariablen setzen (falls nicht durch Unraid konfiguriert)
ENV USERNAME=admin
ENV PASSWORD=secret1991
ENV BASE_DOMAIN=http://localhost:5200
ENV UPLOAD_FOLDER=/app/uploads
ENV PORT=5200

WORKDIR /app

# Kopiere und installiere die Anforderungen
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den Anwendungscode
COPY . /app

# Port als Umgebungsvariable setzen (EXPOSE kann nur statisch sein, daher wird es in app.py dynamisch gelesen)
EXPOSE $PORT

# Starte die Flask-App mit den gesetzten Umgebungsvariablen
CMD ["sh", "-c", "python app.py"]
