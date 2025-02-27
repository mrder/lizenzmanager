FROM python:3

# Entferne Systemvariablen aus der Umgebung, die Unraid erkennt
ENV LANG= C.UTF-8
ENV LC_ALL= C.UTF-8
ENV GPG_KEY= ""
ENV PYTHON_VERSION= ""
ENV PYTHON_SHA256= ""
ENV PYTHONUNBUFFERED=1

# Unsere gewünschten Umgebungsvariablen setzen
ENV USERNAME=admin
ENV PASSWORD=secret1991
ENV BASE_DOMAIN=http://localhost:5200
ENV UPLOAD_FOLDER=/app/uploads
ENV PORT=5200

WORKDIR /app

# Installiere Abhängigkeiten
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den Anwendungscode
COPY . /app

# Mache entrypoint.sh ausführbar
RUN chmod +x /app/entrypoint.sh

# Setze entrypoint.sh als Startbefehl
ENTRYPOINT ["/app/entrypoint.sh"]

# Setze Standardport
EXPOSE 5200
