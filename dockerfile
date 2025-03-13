FROM python:3.11
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV USERNAME=admin
ENV PASSWORD=admin
ENV BASE_DOMAIN=http://localhost:5200
ENV UPLOAD_FOLDER=/app/uploads
ENV PORT=5200
ENV SECRET_KEY=123456
# Persistente Datenbank-URI (Volume wird in docker-compose gemountet)
ENV DATABASE_URI=sqlite:////data/licenses.db
EXPOSE 5200
ENTRYPOINT ["/bin/sh", "./entrypoint.sh"]
