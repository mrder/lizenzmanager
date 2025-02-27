FROM python:3

# Unbuffered stdout/stderr für bessere Logs
ENV PYTHONUNBUFFERED=1

# Stelle sicher, dass nur relevante ENV-Variablen existieren
ENV USERNAME=admin
ENV PASSWORD=secret1991
ENV BASE_DOMAIN=http://localhost:5200
ENV UPLOAD_FOLDER=/app/uploads
ENV PORT=5200

WORKDIR /app

# Kopiere und installiere Python-Abhängigkeiten
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den Anwendungscode
COPY . /app

# Mache das Entry-Skript ausführbar
RUN chmod +x /app/entrypoint.sh

# Setze entrypoint.sh als Startpunkt
ENTRYPOINT ["/app/entrypoint.sh"]

# Setze Standardport (Unraid ignoriert EXPOSE, aber es ist hilfreich für Tests)
EXPOSE 5200
