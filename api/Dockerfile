FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini ./
COPY migrations ./migrations
COPY qorgan ./qorgan
EXPOSE 8000
# Workers share live events through Postgres LISTEN/NOTIFY, so scaling out is safe.
CMD ["uvicorn", "qorgan.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--workers", "4"]
