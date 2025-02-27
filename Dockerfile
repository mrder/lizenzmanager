FROM python:3.9-slim

# Unbuffered stdout/stderr
ENV PYTHONUNBUFFERED=1

# Define Arguments (Used Only at Build Time)
ARG USERNAME=admin
ARG PASSWORD=secret1991
ARG BASE_DOMAIN=http://localhost:5200
ARG UPLOAD_FOLDER=/app/uploads
ARG PORT=5200

# Convert Arguments to Environment Variables (Used at Runtime)
ENV USERNAME=${USERNAME}
ENV PASSWORD=${PASSWORD}
ENV BASE_DOMAIN=${BASE_DOMAIN}
ENV UPLOAD_FOLDER=${UPLOAD_FOLDER}
ENV PORT=${PORT}

WORKDIR /app

# Copy and install dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . /app

# Ensure the correct port is exposed
EXPOSE $PORT

# Start Flask app with proper environment variables
CMD ["sh", "-c", "python app.py"]
