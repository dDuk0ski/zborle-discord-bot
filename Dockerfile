# --- Stage 1: build the Activity frontend ---
FROM node:22-slim AS frontend

WORKDIR /build

# Copy manifests first so npm ci is cached until dependencies actually change.
COPY activity/package.json activity/package-lock.json ./
RUN npm ci

COPY activity/ ./

# The client ID is public and gets baked into the bundle. The client secret is never
# passed here: only the Python backend performs the OAuth2 token exchange.
ARG VITE_DISCORD_CLIENT_ID
ENV VITE_DISCORD_CLIENT_ID=$VITE_DISCORD_CLIENT_ID
RUN npm run build


# --- Stage 2: runtime ---
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

# Served by FastAPI at the root; the path matches ZBORLE_STATIC_DIR's default.
COPY --from=frontend /build/dist ./activity/dist

# Runs as root deliberately. Fly mounts volumes root-owned, so a non-root user cannot
# write to /data without a privilege-dropping entrypoint. Each Fly app is its own
# microVM, so this buys little here and costs a lot of moving parts.
CMD ["python", "main.py"]
