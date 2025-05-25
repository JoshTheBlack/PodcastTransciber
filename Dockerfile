# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Install CORE system dependencies:
# ffmpeg: For audio decoding (this will still be large)
# ca-certificates: For HTTPS
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --- Install gosu ---
# Install curl & gnupg temporarily ONLY for gosu installation, then purge them in THIS layer.
ENV GOSU_VERSION=1.17
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg \
    && set -eux; \
    dpkgArch="$(dpkg --print-architecture)"; \
    if [ "$dpkgArch" = "amd64" ]; then \
        curl -sSL -o /usr/local/bin/gosu "https://github.com/tianon/gosu/releases/download/$GOSU_VERSION/gosu-amd64"; \
        curl -sSL -o /usr/local/bin/gosu.asc "https://github.com/tianon/gosu/releases/download/$GOSU_VERSION/gosu-amd64.asc"; \
    else \
        echo >&2 "Unsupported architecture: $dpkgArch for gosu download"; exit 1; \
    fi; \
    export GNUPGHOME="$(mktemp -d)"; \
    gpg --batch --keyserver hkps://keys.openpgp.org --recv-keys B42F6819007F00F88E364FD4036A9C25BF357DD4; \
    gpg --batch --verify /usr/local/bin/gosu.asc /usr/local/bin/gosu; \
    gpgconf --kill all; rm -rf "$GNUPGHOME" /usr/local/bin/gosu.asc; \
    chmod +x /usr/local/bin/gosu; gosu --version; \
    # Purge temporary dependencies FOR GOSU in the SAME RUN command
    apt-get purge -y --auto-remove curl gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*
# --- End gosu install ---

# --- Create default non-root user and group ---
ENV APP_USER=appuser
ENV APP_GROUP=appgroup
# Default UID, entrypoint uses PUID env var to override
ENV DEFAULT_UID=1000
# Default GID, entrypoint uses PGID env var to override
ENV DEFAULT_GID=1000
RUN groupadd -g ${DEFAULT_GID} ${APP_GROUP} \
    && useradd -u ${DEFAULT_UID} -g ${APP_GROUP} -m -s /bin/bash ${APP_USER}

# Copy the core requirements file (small dependencies for entrypoint venv setup)
COPY ./app/requirements-core.txt /app/requirements-core.txt

# Copy the application code
COPY ./app /app

# Copy the new entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Ownership of /app for application code. /out and /data_persistent handled by entrypoint.
RUN chown -R ${APP_USER}:${APP_GROUP} /app
RUN mkdir -p /out && chown ${APP_USER}:${APP_GROUP} /out # App output dir

# --- Environment Variables (Defaults for runtime, read by entrypoint & app) ---
ENV PYTHONUNBUFFERED=1
ENV TZ="UTC"

# Defaults that entrypoint.sh will use if not overridden by user:
ENV TRANSCRIPTION_ENGINE="faster-whisper"
ENV DEVICE="cpu"
ENV WHISPER_MODEL="base"
ENV PUID=${DEFAULT_UID}
ENV PGID=${DEFAULT_GID}

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "main.py"]