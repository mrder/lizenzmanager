FROM python:3.9-slim

# Unbuffered stdout/stderr
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Kopiere und installiere die Anforderungen
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den Anwendungscode
COPY . /app

# Standardport (wird in der app.py über ENV PORT verwendet)
EXPOSE 5200

CMD ["python", "app.py"]
