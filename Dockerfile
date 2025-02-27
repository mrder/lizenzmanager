FROM python:3

# Unbuffered stdout/stderr
ENV PYTHONUNBUFFERED=1

# Setze nur die relevanten Umgebungsvariablen
ENV USERNAME=admin
ENV PASSWORD=secret1991
ENV BASE_DOMAIN=http://localhost:5200
ENV UPLOAD_FOLDER=/app/uploads
ENV PORT=5200

WORKDIR /app

# Installiere Python-Abhängigkeiten
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den Anwendungscode
COPY . /app

# Mache entrypoint.sh ausführbar und setze sie als Startskript
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]

# Setze Standardport
EXPOSE 5200
