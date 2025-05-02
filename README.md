# Podcast Transcriber using OpenAI Whisper

  

[![Docker Pulls](https://img.shields.io/docker/pulls/joshtheblack/podcast-transcriber.svg)](https://hub.docker.com/r/joshtheblack/podcast-transcriber) [![GitHub Actions Workflow Status](https://github.com/JoshTheBlack/PodcastTransciber/actions/workflows/docker-build-push.yml/badge.svg)](https://github.com/JoshTheBlack/PodcastTransciber/actions/workflows/docker-build-push.yml) 
This Docker container continuously monitors one or more podcast RSS feeds for new episodes. When a new episode is detected within a configurable lookback period (default 7 days), it downloads the audio file (MP3), transcribes it using OpenAI's Whisper model, and saves the output. 

## Features
* **Continuous Monitoring:** Runs indefinitely, checking feeds periodically.
* **Whisper Transcription:** Utilizes the `openai-whisper` library for transcription.
* **Configurable Feeds:** Monitor multiple podcast feeds.
* **Selectable Whisper Model:** Choose model size based on accuracy/resource needs (tiny, base, small, medium, large).
* **Configurable Lookback:** Only processes recently published episodes on startup or after downtime.
* **Organized Output:** Saves transcripts (`.txt`) and audio files (`.mp3`) to separate subdirectories.
* **State Tracking:** Remembers processed episodes to avoid redundant work.
* **Debug Logging:** Optional verbose logging for troubleshooting.
## Prerequisites
* Docker installed on your system (or Unraid server).

## Installation
Pull the pre-built image directly from Docker Hub:
```bash
docker pull joshtheblack/podcast-transcriber:latest
```
## Configuration

Configure the container using environment variables:

| Variable                  | Description                                                                                                                                  | Default    | Required | Example                                                            |
| :------------------------ | :------------------------------------------------------------------------------------------------------------------------------------------- | :--------- | :------- | :----------------------------------------------------------------- |
| `PODCAST_FEEDS`           | Semicolon-separated (`;`) list of podcast RSS feed URLs.                                                                                     | `""`       | **Yes**  | `https://url1.com/feed.xml;https://url2.com/rss`                   |
| `TZ`                      | Set the container's timezone (use standard tz database names). Important for accurate lookback period calculations and logs.                 | `UTC`      | **No**   | `America/New_York`                                                 |
| `WHISPER_MODEL`           | The Whisper model to use (`tiny`, `base`, `small`, `medium`, `large`). Larger models are more accurate but require more CPU/RAM/GPU VRAM.    | `base`     | No       | `small`                                                            |
| `CHECK_INTERVAL_SECONDS`  | How often (in seconds) to check the feeds for new episodes.                                                                                  | `3600`     | No       | `1800` (30 minutes)                                                |
| `LOOKBACK_DAYS`           | How many days back to check for unprocessed episodes when starting or checking feeds.                                                        | `7`        | No       | `14`                                                               |
| `DEBUG_LOGGING`           | Set to `true` for verbose Whisper output and detailed DEBUG level logs. Set to `false` for standard INFO level logs.                         | `false`    | No       | `true`                                                             |

  **Note on Whisper Models & Resources:** Larger models like `medium` and `large` require significant RAM (several GB) and are much slower on CPU. Using a compatible NVIDIA GPU significantly speeds up transcription (requires a different setup/base image not covered by this basic image).

## Usage Examples

You **must** map a volume to `/out` inside the container to retrieve your transcriptions and audio files, and to persist the state file (`.processed_episodes.log`) between container restarts.

### Using `docker run`

Create a directory on your host to store the output
```bash
mkdir ./output
```
# Run the container

```
docker run -d \
  --name podcast-transcriber \
  --restart=unless-stopped \
  -v "$(pwd)/output:/out" \
  -e PODCAST_FEEDS="YOUR_FEED_URL_1;YOUR_FEED_URL_2" \
  -e TZ="America/New_York" \
  -e WHISPER_MODEL="base" \
  -e CHECK_INTERVAL_SECONDS="3600" \
  -e LOOKBACK_DAYS="7" \
  -e DEBUG_LOGGING="false" \
  joshtheblack/podcast-transcriber:latest
```

* Replace `YOUR_FEED_URL_1;YOUR_FEED_URL_2` with your actual feed URLs.
* Replace `America/New_York` with your [local timezone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).
* Adjust other environment variables (`-e`) as needed.
* `$(pwd)/output` maps a directory named `output` in your current working directory on the host to `/out` in the container. Change the host path as desired.
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
      # Map a local directory './output' to the container's /out directory
      - ./output:/out
    environment:
      # --- Required ---
      - PODCAST_FEEDS=YOUR_FEED_URL_1;YOUR_FEED_URL_2
      # --- Recommended ---
      - TZ=America/New_York
      # --- Optional ---
      - WHISPER_MODEL=base
      - CHECK_INTERVAL_SECONDS=3600
      - LOOKBACK_DAYS=7
      - DEBUG_LOGGING=false
    # Optional: If you have a compatible NVIDIA GPU and drivers installed
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - driver: nvidia
    #           count: 1
    #           capabilities: [gpu]

# If not using a bind mount like above, define a named volume:
# volumes:
#  output:
```

  
- Create the ./output directory first if using bind mount: mkdir ./output
Run using: docker compose up -d # (or docker-compose up -d for older versions)
* Replace placeholders in the `environment` section.
* Create an `output` directory in the same location as your `docker-compose.yml` file if using the bind mount example.
* Run `docker compose up -d` (or `docker-compose up -d`) to start the container.
### Setting Up on Unraid
Unraid uses Docker through its web UI.
1.  **Go to Docker Tab:** Navigate to the "Docker" tab in your Unraid web UI.
2.  **Add Container:** Scroll to the bottom and click "Add Container".
3.  **Fill Basic Settings:**
    * **Name:** Give it a name (e.g., `Podcast-Transcriber`).
    * **Repository:** Enter `joshtheblack/podcast-transcriber:latest`.
    * **Network Type:** `Bridge` is usually fine.
    * **Restart Policy:** Set this to `Unless Stopped`.
4. *Add Volume Mapping:**
    * Click "Add another Path, Port, Variable, Label or Device".
    * **Config Type:** `Path`
    * **Name:** `Output Files` (or similar)
    * **Container Path:** `/out`
    * **Host Path:** Choose a path on your Unraid server where you want the transcripts and MP3s stored. Example: `/mnt/user/appdata/podcast-transcriber/output/` (Make sure the `appdata/podcast-transcriber` part exists or adjust as needed).
    * **Access Mode:** `Read/Write`
5.  **Add Environment Variables:**
    * Click "Add another Path, Port, Variable, Label or Device" repeatedly for each variable you need to set.
    * **Config Type:** `Variable`
    * **Required:**
        * **Name:** `PODCAST_FEEDS` | **Key:** `PODCAST_FEEDS` | **Value:** `YOUR_FEED_URL_1;YOUR_FEED_URL_2` (Enter your feeds)
    * **Recommended:**
        * **Name:** `Timezone` | **Key:** `TZ` | **Value:** `America/New_York` (Enter your timezone)
    * **Optional (Add as needed):**
        * **Name:** `Whisper Model` | **Key:** `WHISPER_MODEL` | **Value:** `base` (or `small`, etc.)
        * **Name:** `Check Interval` | **Key:** `CHECK_INTERVAL_SECONDS` | **Value:** `3600`
        * **Name:** `Lookback Days` | **Key:** `LOOKBACK_DAYS` | **Value:** `7`
        * **Name:** `Debug Logging` | **Key:** `DEBUG_LOGGING` | **Value:** `false` (or `true`)
6.  **Apply and Start:** Click "Apply" at the bottom of the page. Unraid will pull the image and start the container.
7.  **Check Logs:** You can check the container's logs by clicking its icon on the Docker tab and selecting "Logs".

## Output Structure
Files will be saved within the directory you mapped to `/out` on your host system:

<your_host_output_directory>/

├── .processed_episodes.log   # State file tracking processed episodes

├── mp3/                      # Directory for original audio files

│   └── episode_title_1.mp3

│   └── episode_title_2.mp3

│   └── ...

└── transcripts/              # Directory for transcription text files

    └── episode_title_1.txt

    └── episode_title_2.txt

    └── ...