# Podcast Transcriber using faster-whisper

[![Docker Pulls](https://img.shields.io/docker/pulls/joshtheblack/podcast-transcriber.svg)](https://hub.docker.com/r/joshtheblack/podcast-transcriber)
[![GitHub Actions Workflow Status](https://github.com/JoshTheBlack/PodcastTransciber/actions/workflows/docker-build-push.yml/badge.svg)](https://github.com/JoshTheBlack/PodcastTransciber/actions/workflows/docker-build-push.yml)

This Docker container continuously monitors one or more podcast RSS feeds for new episodes. When a new episode is detected within a configurable lookback period (default 7 days), it downloads the audio file (MP3), transcribes it using `faster-whisper` (a CTranslate2 reimplementation of Whisper) for faster and more memory-efficient transcription, and saves the output.

## Features

* **Continuous Monitoring:** Runs indefinitely, checking feeds periodically.
* **Selectable Transcription Engine:** Choose between `faster-whisper` (default, for speed and efficiency) and `openai-whisper`.
* **Import Folder:** Prioritized processing of audio files dropped into a specified local directory.
* **Efficient Whisper Transcription:** Utilizes `faster-whisper` for improved speed and lower memory usage.
* **Configurable Feeds:** Monitor multiple podcast feeds.
* **Selectable Whisper Model:** Choose model size based on accuracy/resource needs.
* **Configurable Lookback:** Only processes recently published episodes.
* **Organized Output:** Saves transcripts and optionally audio files.
* **State Tracking:** Remembers processed episodes.
* **CPU/GPU Support:** Choose device (`cpu` or `cuda`).
* **Compute Type Selection:** Optimize for speed/memory.
* **Debug Logging:** Optional detailed logging.
* **Conditional MP3 Retention:** Choose to keep MP3 files after transcription (default is to delete).
* **Discord Webhook Notifications:** Optionally send transcripts to Discord.

## Prerequisites

* Docker installed.
* For GPU acceleration: NVIDIA GPU, drivers, and NVIDIA Container Toolkit.

## Installation

Pull the pre-built image directly from Docker Hub:

```bash
docker pull joshtheblack/podcast-transcriber:latest
```

## Configuration

Configure the container using environment variables:

| Variable                 | Description                                                                                                                                                         | Default    | Required | Example                                                           |
| :----------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------ | :--------- | :------- | :---------------------------------------------------------------- |
| `PODCAST_FEEDS`          | Semicolon-separated (`;`) list of podcast RSS feed URLs.                                                                                                            | `""`       | **Yes** | `https://url1.com/feed.xml;https://url2.com/rss`                  |
| `IMPORT_DIR`          | Path to a local directory to monitor for audio files to import and transcribe (e.g., /import). Files here are processed with priority.	|""                                                                                                            | `""`       | No (but PODCAST_FEEDS or IMPORT_DIR should be set) | `/mnt/user/import_audio`                  |
| `TZ`                     | Set the container's timezone (use standard tz database names). Important for accurate lookback period calculations and logs.                                          | `UTC`      | No       | `America/New_York`                                                |
| `PUID`    | Set the user ID the container runs as | `99` | No | `99`  |
| `PGID`    | Set the user ID the container runs as | `100` | No | `100`  |
| `TRANSCRIPTION_ENGINE`    | Transcription engine to use: faster-whisper or openai-whisper | `faster-whispe` | No | `openai-whisper`  |
| `WHISPER_MODEL`          | The faster-whisper model to use (e.g., `tiny`, `base`, `small`, `medium`, `large-v2`, `large-v3`, `distil-large-v2`). See faster-whisper docs for more options. | `base`     | No       | `small` or `large-v3`                                             |
| `DEVICE`                 | Device to run inference on (`cpu`, `cuda`). Using `cuda` requires host NVIDIA drivers & NVIDIA Container Toolkit setup.                                             | `cpu`      | No       | `cuda`                                                            |
| `COMPUTE_TYPE`           | For faster-whisper only. Data type/quantization (e.g., default, float16, int8).         | `default`  | No       | `float16` (GPU), `int8` (GPU/CPU)                             |
| `CHECK_INTERVAL_SECONDS` | How often (in seconds) to check the feeds for new episodes.                                                                                                         | `3600`     | No       | `1800` (30 minutes)                                               |
| `LOOKBACK_DAYS`          | How many days back to check for unprocessed episodes when starting or checking feeds.                                                                               | `7`        | No       | `14`                                                              |
| `DEBUG_LOGGING`          | Set to `true` for detailed script DEBUG logs. Note: faster-whisper itself doesn't have verbose transcription output like openai-whisper.                           | `false`    | No       | `true`                                                            |
| `KEEP_MP3`          | Set to `true` to keep MP3 files after transcription. If false or not set, MP3s are deleted.                          | `false`    | No       | `true`                                                            |
| `DISCORD_WEBHOOK_URL`          | Discord webhook URL for transcript notifications.                          | `""`    | No       | `https://discord.com/api/webhooks/your_id/your_token`                                                            |

**Note on Models, Devices, and Compute Types:**
* `faster-whisper` is generally faster and uses less memory than `openai-whisper`, especially on CPU.
* Larger models (`medium`, `large-v*`) are more accurate but require more resources.
* Using `DEVICE="cuda"` requires a compatible NVIDIA GPU, correctly installed drivers on the host, and the NVIDIA Container Toolkit configured for Docker.
* `COMPUTE_TYPE` allows further optimization:
    * `float16` or `int8_float16`: Often faster on compatible GPUs, use less VRAM than `float32`.
    * `int8`: Fastest, lowest memory usage (CPU/GPU), but might have a slight impact on accuracy compared to float types. Requires CPU support for acceleration.
    * `default`: faster-whisper chooses based on device/model (often `float32` on CPU, potentially `float16` on GPU).
    * Consult the [faster-whisper documentation](https://github.com/guillaumekln/faster-whisper#compute-type) for details.

## Usage Examples

You **must** map a volume to `/out` inside the container to retrieve your transcriptions and audio files, and to persist the state file (`.processed_episodes.log`) between container restarts.

### Using `docker run`

# Run the container (CPU Example)
```bash
mkdir -p ./output ./import_folder # Create host directories

# Example: Podcasts and Import Folder, faster-whisper (default)
docker run -d \
  --name podcast-transcriber \
  --restart=unless-stopped \
  -v "{pwd}\output\:/out" \
  -v "{pwd}\import:/import" \
  -e PODCAST_FEEDS="YOUR_FEED_URL_1" \
  -e IMPORT_DIR="/import" \
  -e TZ="America/New_York" \
  -e PUID=1000 \
  -e PGID=1000 \
  -e WHISPER_MODEL="base" \
  -e KEEP_MP3="false" \
  -e DISCORD_WEBHOOK_URL="YOUR_DISCORD_WEBHOOK_URL" \
  joshtheblack/podcast-transcriber:latest

# Example: Import Folder Only, openai-whisper, GPU
docker run -d --gpus all \
  --name podcast-transcriber-importer \
  --restart=unless-stopped \
  -v "<span class="math-inline">\(pwd\)/output\:/out" \
  -v "</span>(pwd)/import_folder:/import" \
  -e IMPORT_DIR="/import" \
  -e TRANSCRIPTION_ENGINE="openai-whisper" \
  -e WHISPER_MODEL="medium" \
  -e DEVICE="cuda" \
  -e TZ="America/New_York" \
  joshtheblack/podcast-transcriber:latest
```

* Replace `YOUR_FEED_URL_1;YOUR_FEED_URL_2` and `America/New_York` with your values.
* Adjust `WHISPER_MODEL`, `DEVICE`, `COMPUTE_TYPE` and other optional variables as needed.
* Ensure the host path for the volume (`-v`) exists and is correct for your system (e.g., `${PWD}/output` in PowerShell, `/path/to/output` on Linux).

### Using `docker-compose.yml`

Create a `docker-compose.yml` file like this:

```yaml
version: '3.8'

services:
  podcast-transcriber:
    image: joshtheblack/podcast-transcriber:latest
    container_name: podcast-transcriber
    restart: unless-stopped
    volumes:
      - ./output:/out            # For transcripts, state, kept MP3s
      - ./import_folder:/import  # For audio files to import
    environment:
      # --- Required ---
      - PODCAST_FEEDS=YOUR_FEED_URL_1;YOUR_FEED_URL_2 # Optional
      - IMPORT_DIR=/import                           # Optional
      # --- General Settings ---
      - TZ=America/New_York
      - PUID=99 # Your user's PUID
      - PGID=100 # Your user's PGID
      - DEBUG_LOGGING=false
      - DISCORD_WEBHOOK_URL= # Optional
      # --- Transcription Engine Settings ---
      - TRANSCRIPTION_ENGINE=faster-whisper # or "openai-whisper"
      - WHISPER_MODEL=base
      - DEVICE=cpu                        # or "cuda" for GPU
      - COMPUTE_TYPE=default              # Only for faster-whisper
      # --- Podcast Specific Settings ---
      - CHECK_INTERVAL_SECONDS=3600
      - LOOKBACK_DAYS=7
      - KEEP_MP3=false                    # For podcast MP3s
    # Optional: GPU Deployment (requires nvidia-container-toolkit)
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - driver: nvidia
    #           count: 1 # or specific GPU IDs: capabilities: [gpu]
    #           capabilities: [gpu]
```

If not using a bind mount like above, define a named volume:
```yaml
volumes:
 output:
```

Create the ./output directory first: mkdir ./output
Run using: docker compose up -d # (or docker-compose up -d for older versions)


* Replace placeholders in the `environment` section.
* Uncomment and configure the `deploy` section if using a GPU with docker compose swarm mode or similar orchestration. For single-node GPU access with compose, adding `runtime: nvidia` under the service might be needed depending on Docker version, or rely on the default Docker daemon configuration for NVIDIA runtime.
* Run `docker compose up -d` to start.

### Setting Up on Unraid

Unraid uses Docker through its web UI.

1.  **Go to Docker Tab:** Navigate to the "Docker" tab in your Unraid web UI.
2.  **Add Container:** Scroll to the bottom and click "Add Container".
3.  **Fill Basic Settings:**
    * **Name:** `Podcast-Transcriber`
    * **Repository:** `joshtheblack/podcast-transcriber:latest`
    * **Network Type:** `Bridge`
    * **Restart Policy:** `Unless Stopped`
4.  **Add Volume Mapping:**
    * Click "Add another Path, Port, Variable, Label or Device".
    * **Config Type:** `Path`
    * **Name:** `Output Files` (or similar)
    * **Container Path:** `/out`
    * **Host Path:** Choose a path on your Unraid server where you want the transcripts and MP3s stored. Example: `/mnt/user/appdata/podcast-transcriber/output/` (Make sure the `appdata/podcast-transcriber` part exists or adjust as needed).
    * **Access Mode:** `Read/Write`
5.  **Add Environment Variables:**
    * Click "Add another Path, Port, Variable, Label or Device" repeatedly for each variable you need to set.
    * **Config Type:** `Variable`
    * **Required:**
        * **Name:** `PODCAST_FEEDS` | **Key:** `PODCAST_FEEDS` | **Value:** `YOUR_FEED_URL_1;...` (Enter your feeds)
    * **Recommended:**
        * **Name:** `Timezone` | **Key:** `TZ` | **Value:** `America/New_York` (Your timezone)
        * **Name:** `User ID`  | **Key:** `PUID`    | **Value** `99`
        * **Name:** `Group ID`  | **Key:** `PGID`    | **Value** `100`
    * **Optional:**
        * **Name:** `Whisper Model` | **Key:** `WHISPER_MODEL` | **Value:** `base` (or `small`, `medium`, `large-v3`...)
        * **Name:** `Device` | **Key:** `DEVICE` | **Value:** `cpu` (or `cuda` if GPU configured on host)
        * **Name:** `Compute Type` | **Key:** `COMPUTE_TYPE` | **Value:** `default` (or `float16`, `int8`...)
        * **Name:** `Check Interval` | **Key:** `CHECK_INTERVAL_SECONDS` | **Value:** `3600`
        * **Name:** `Lookback Days` | **Key:** `LOOKBACK_DAYS` | **Value:** `7`
        * **Name:** `Debug Logging` | **Key:** `DEBUG_LOGGING` | **Value:** `false` (or `true`)
6.  **(GPU Only on Unraid):** If using `DEVICE="cuda"`, you need the "Nvidia Driver" plugin installed on Unraid. In the "Extra Parameters" field when adding the container, you might need to add `--gpus all` (or specific GPU UUIDs). Consult Unraid community forums for current best practices on passing GPUs to Docker containers.
7.  **Apply and Start:** Click "Apply".
8.  **Check Logs:** Use the Unraid Docker UI to view logs.

## Output Structure

Files will be saved within the directory you mapped to `/out` on your host system:

```
<your_host_output_directory>/
  ├── .processed_episodes.log   # State file tracking processed episodes
  ├── mp3/                      # Directory for original audio files
  │   └── episode_title_1.mp3
  │   └── episode_title_2.mp3
  │   └── ...
  └── transcripts/              # Directory for transcription text files
      └── episode_title_1.txt
      └── episode_title_2.txt
      └── ...

<your_host_import_directory>/   # Mapped to /import (e.g., /import_folder)
  ├── audiofile_to_process.mp3  # Drop files here
  └── another_audio.wav
  └── .processing_tmp/          # Internal temporary folder, do not manually add files here
```