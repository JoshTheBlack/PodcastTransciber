# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies:
# ffmpeg: Still needed for robust audio decoding by the script before passing to whisper
# git: Might be needed by pip for installing certain dependencies
# ca-certificates: Good practice for HTTPS requests (feeds, downloads)
# CTranslate2 (faster-whisper's engine) might benefit from CPU features like AVX/AVX2
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Using --no-cache-dir reduces image size
# Note: This will install faster-whisper and its dependencies like ctranslate2, transformers
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Python script into the container at /app
COPY monitor.py .

# Create the output directories (script will ensure they exist too)
RUN mkdir -p /out/transcripts /out/mp3

# --- Environment Variables ---
# Mandatory
ENV PODCAST_FEEDS=""

# Optional - Faster-Whisper Specific
ENV WHISPER_MODEL="base"    # Options: tiny, base, small, medium, large, large-v2, large-v3, or path to converted model
ENV DEVICE="cpu"            # Device: "cpu", "cuda"
ENV COMPUTE_TYPE="default"  # Compute type: "default", "int8", "int8_float16", "int16", "float16", "float32" (see faster-whisper docs)

# Optional - Script Behavior
ENV CHECK_INTERVAL_SECONDS=3600
ENV LOOKBACK_DAYS=7
ENV DEBUG_LOGGING="false"   # Controls Python logging level (INFO vs DEBUG)
ENV TZ="UTC"                # Set Timezone, e.g., America/New_York

# Force python stdout/stderr streams to be unbuffered
ENV PYTHONUNBUFFERED=1

# Define the command to run the Python script when the container starts
CMD ["python", "monitor.py"]