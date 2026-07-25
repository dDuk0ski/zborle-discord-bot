FROM python:3.13-slim

# PYTHONUNBUFFERED matters here: without it, log lines sit in a buffer and `fly logs`
# shows nothing until the process exits.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./
COPY zborle_bot/ ./zborle_bot/
COPY data/ ./data/
COPY fonts/ ./fonts/

# Runs as root deliberately. Fly mounts volumes root-owned, so a non-root user cannot
# write to /data without a privilege-dropping entrypoint. Each Fly app is its own
# microVM, so this buys little here and costs a lot of moving parts.
CMD ["python", "main.py"]
