# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required by whisper (ffmpeg)
# Also install git, necessary for whisper installation in some cases
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Using --no-cache-dir reduces image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Python script into the container at /app
COPY monitor.py .

# Create the output directory
RUN mkdir /out

# Environment variable for podcast feeds (can be overridden at runtime)
# Example format: "URL1;URL2;URL3"
ENV PODCAST_FEEDS=""
# Optional: Specify Whisper model (e.g., tiny, base, small, medium, large). 'base' is a good default.
ENV WHISPER_MODEL="base"
# Optional: Set check interval in seconds (default: 1 hour)
ENV CHECK_INTERVAL_SECONDS=3600
# Force python stdout/stderr streams to be unbuffered
# This helps ensure logs appear in Docker immediately
ENV PYTHONUNBUFFERED=1


# Define the command to run the Python script when the container starts
CMD ["python", "monitor.py"]