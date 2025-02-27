FROM python:3.9-slim
ENV USERNAME=admin
ENV PASSWORD=secret1991
ENV BASE_DOMAIN=http://localhost:5200
ENV UPLOAD_FOLDER=/app/uploads
ENV PORT=5200
COPY . /app
WORKDIR /app
CMD ["python", "app.py"]
