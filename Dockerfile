FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_PATH=/data/aqua.sqlite3
COPY app.py ./
COPY static/ ./static/
RUN mkdir -p /data
EXPOSE 8000
CMD ["python3", "app.py"]
