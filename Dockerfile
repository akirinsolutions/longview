# Longview — the filings, decoded. One process, one small dependency story.
#
# Railway (or any container host): the app is a plain FastAPI/uvicorn
# process. Disk persistence is for the per-user files — mount a volume
# at /data and set the env vars below (see the README's deploy section).
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
# pytest is in requirements for tests; it ships in the image but never loads.
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LONGVIEW_VAULT=/data/longview.json \
    LONGVIEW_ACCOUNTS=/data/accounts.json \
    LONGVIEW_SECRET=/data/secret.key \
    LONGVIEW_USERS_DIR=/data/users

EXPOSE 8000
# $PORT is set by the platform (Railway, Render, Fly.io, ...) — the fallback
# matches the README's own examples and a plain `docker run`.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
