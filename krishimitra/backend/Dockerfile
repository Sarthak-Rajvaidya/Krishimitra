FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m app && mkdir -p /srv/storage && chown -R app /srv/storage
USER app
EXPOSE 8000
# 4 workers x (pool 10 + overflow 10) = up to 80 DB connections per container; size Postgres accordingly.
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "4", "-b", "0.0.0.0:8000", "--timeout", "60", "--graceful-timeout", "30"]
