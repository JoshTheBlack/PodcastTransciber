# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies:
# ffmpeg: For audio decoding
# git: May be needed by pip
# ca-certificates: For HTTPS
# gosu: For changing user in entrypoint script
# curl & gpg: Needed temporarily to install gosu securely
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    ca-certificates \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# --- Install gosu ---
ENV GOSU_VERSION=1.17
RUN set -eux; \
    # Fetch gosu binary for amd64 architecture
    dpkgArch="$(dpkg --print-architecture)"; \
    if [ "$dpkgArch" = "amd64" ]; then \
        curl -sSL -o /usr/local/bin/gosu "https://github.com/tianon/gosu/releases/download/$GOSU_VERSION/gosu-amd64"; \
        curl -sSL -o /usr/local/bin/gosu.asc "https://github.com/tianon/gosu/releases/download/$GOSU_VERSION/gosu-amd64.asc"; \
    else \
        # Add other architectures here if needed (e.g., arm64)
        echo >&2 "Unsupported architecture: $dpkgArch for gosu download"; \
        exit 1; \
    fi; \
    \
    # Verify the signature
    export GNUPGHOME="$(mktemp -d)"; \
    # Obtain the signing key (Tianon Gravi's key, used for gosu releases)
    gpg --batch --keyserver hkps://keys.openpgp.org --recv-keys B42F6819007F00F88E364FD4036A9C25BF357DD4; \
    gpg --batch --verify /usr/local/bin/gosu.asc /usr/local/bin/gosu; \
    gpgconf --kill all; \
    rm -rf "$GNUPGHOME" /usr/local/bin/gosu.asc; \
    \
    # Make executable and cleanup
    chmod +x /usr/local/bin/gosu; \
    gosu --version; \
    apt-get purge -y --auto-remove curl gnupg; \
    rm -rf /var/lib/apt/lists/*
# --- End gosu install ---

# --- Create default non-root user and group ---
ENV APP_USER=appuser
ENV APP_GROUP=appgroup
ENV DEFAULT_UID=1000
ENV DEFAULT_GID=1000
RUN groupadd -g ${DEFAULT_GID} ${APP_GROUP} \
    && useradd -u ${DEFAULT_UID} -g ${APP_GROUP} -m -s /bin/bash ${APP_USER}
# --- End user creation ---

# Copy requirements first for layer caching
COPY requirements.txt .
# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code from your local 'app' directory to /app in the container
COPY ./app .

# Copy the entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

# Make entrypoint executable
RUN chmod +x /usr/local/bin/entrypoint.sh

# Set /app ownership (applies to files copied from ./app)
# This is good practice, though entrypoint.sh also handles ownership of /app and /out at runtime
RUN chown -R ${APP_USER}:${APP_GROUP} /app

# Create output directories and set permissions
# Note: entrypoint.sh also ensures ownership of /out at runtime, which is more robust for mounted volumes.
# This step during build ensures the paths exist if not mounted over.
RUN mkdir -p /out/transcripts /out/mp3 \
    && chown -R ${APP_USER}:${APP_GROUP} /out

# --- Environment Variables (Defaults) ---
# These are primarily for documentation and defaults; they will be set by the user at runtime.
ENV PODCAST_FEEDS=""
ENV WHISPER_MODEL="base"
ENV DEVICE="cpu"
ENV COMPUTE_TYPE="default"
ENV CHECK_INTERVAL_SECONDS=3600
ENV LOOKBACK_DAYS=7
ENV DEBUG_LOGGING="false"
ENV TZ="UTC"
ENV PUID=1000
ENV PGID=1000
ENV IMPORT_DIR="/import"
ENV TRANSCRIPTION_ENGINE="faster-whisper"

ENV PYTHONUNBUFFERED=1

# Set the entrypoint script
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Default command (passed to entrypoint as $@)
CMD ["python", "main.py"] # MODIFIED: Changed monitor.py to main.py