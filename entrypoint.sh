#!/bin/bash
set -e # Exit immediately if a command exits with a non-zero status.
# set -x # Uncomment for verbose debugging of this script

# --- Configuration ---
PERSISTENT_DATA_DIR_MOUNT="/data_persistent" # User mounts their host dir here
VENV_PATH="$PERSISTENT_DATA_DIR_MOUNT/venv"
MODEL_CACHE_ROOT="$PERSISTENT_DATA_DIR_MOUNT/models"
FASTER_WHISPER_CACHE_DIR="$MODEL_CACHE_ROOT/faster_whisper_models"
OPENAI_WHISPER_CACHE_DIR="$MODEL_CACHE_ROOT/openai_whisper_models"

PYTHON_FROM_VENV="$VENV_PATH/bin/python"
PIP_FROM_VENV="$VENV_PATH/bin/pip"

DESIRED_ENGINE="${TRANSCRIPTION_ENGINE:-faster-whisper}"
DESIRED_DEVICE="${DEVICE:-cpu}"

PYTORCH_VARIANT_FILE="$VENV_PATH/.pytorch_variant"

# --- User/Group Setup ---
UNAME=${APP_USER:-appuser}
GNAME=${APP_GROUP:-appgroup}
# Safely get PUID/PGID, defaulting if Python/config.py is not available yet or PUID/PGID are invalid
TARGET_PUID="${PUID:-1000}" # Default to 1000 if PUID not set
TARGET_PGID="${PGID:-1000}" # Default to 1000 if PGID not set

# Validate PUID/PGID are numbers; fallback to safe defaults
if ! [[ "$TARGET_PUID" =~ ^[0-9]+$ ]]; then
    echo "Warning: PUID '$TARGET_PUID' is not a number. Using 99." >&2
    TARGET_PUID=99
fi
if ! [[ "$TARGET_PGID" =~ ^[0-9]+$ ]]; then
    echo "Warning: PGID '$TARGET_PGID' is not a number. Using 100." >&2
    TARGET_PGID=100
fi

echo "Starting container. Target UID: ${TARGET_PUID}, GID: ${TARGET_PGID}"
echo "Desired transcription engine: $DESIRED_ENGINE, Device: $DESIRED_DEVICE"
echo "Persistent data directory targeted at: $PERSISTENT_DATA_DIR_MOUNT"

# --- Directory and Permissions Setup (as root) ---
echo "Creating persistent directory structure (as root)..."
mkdir -p "$VENV_PATH" \
           "$OPENAI_WHISPER_CACHE_DIR" \
           "$FASTER_WHISPER_CACHE_DIR" \
           "$MODEL_CACHE_ROOT" # Ensure parent model dir exists

echo "Attempting to set ownership of $PERSISTENT_DATA_DIR_MOUNT to ${TARGET_PUID}:${TARGET_PGID}..."
if chown -R "${TARGET_PUID}:${TARGET_PGID}" "$PERSISTENT_DATA_DIR_MOUNT"; then
    echo "Successfully set ownership for $PERSISTENT_DATA_DIR_MOUNT."
    # Verify by listing
    ls -ld "$PERSISTENT_DATA_DIR_MOUNT"
    ls -ld "$VENV_PATH" || echo "Warning: $VENV_PATH not found after mkdir."
    ls -ld "$MODEL_CACHE_ROOT" || echo "Warning: $MODEL_CACHE_ROOT not found after mkdir."
    ls -ld "$FASTER_WHISPER_CACHE_DIR" || echo "Warning: $FASTER_WHISPER_CACHE_DIR not found after mkdir."
else
    echo "ERROR: Failed to set ownership for $PERSISTENT_DATA_DIR_MOUNT. Exit code: $?."
    echo "       This is likely due to permissions on the host's mounted directory."
    echo "       The application may fail to write to this directory."
    # Consider exiting: exit 1
fi

# --- Venv and Dependency Setup (still as root, pip will handle venv context) ---
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    echo "Virtual environment not found at $VENV_PATH. Creating (as root, will chown)..."
    python3 -m venv "$VENV_PATH"
    chown -R "${TARGET_PUID}:${TARGET_PGID}" "$VENV_PATH" # Chown venv specifically after creation
    echo "Virtual environment created and ownership set."
    echo "Installing core Python packages into venv..."
    # Run pip as the target user to ensure venv packages are owned correctly from the start if possible,
    # OR ensure venv dir is fully writable by target user before pip install.
    # Simpler: install as root into root-created venv, then chown the whole venv. This was done above.
    "$PIP_FROM_VENV" install --no-cache-dir -r /app/requirements-core.txt
    NEEDS_PYTORCH_CHECK=true
else
    echo "Virtual environment found at $VENV_PATH."
    NEEDS_PYTORCH_CHECK=false
fi

INSTALLED_PYTORCH_VARIANT=""
if [ -f "$PYTORCH_VARIANT_FILE" ]; then
    INSTALLED_PYTORCH_VARIANT=$(cat "$PYTORCH_VARIANT_FILE")
fi

if [ "$DESIRED_ENGINE" = "openai-whisper" ]; then
    echo "OpenAI-Whisper engine selected."
    CURRENT_PYTORCH_SETUP_FOR="cpu" # Assume CPU unless CUDA detected and desired
    TORCH_INSTALL_CMD="$PIP_FROM_VENV install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu"

    if [ "$DESIRED_DEVICE" = "cuda" ]; then
        if command -v nvidia-smi &> /dev/null && nvidia-smi -L &> /dev/null; then
            echo "CUDA device requested and nvidia-smi found. Preparing for GPU PyTorch."
            CURRENT_PYTORCH_SETUP_FOR="cu118" # Example, make this dynamic if needed
            TORCH_INSTALL_CMD="$PIP_FROM_VENV install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu118"
        else
            echo "Warning: CUDA device requested, but nvidia-smi not found or no GPU detected. Falling back to CPU PyTorch."
        fi
    fi

    if [ "$NEEDS_PYTORCH_CHECK" = "true" ] || [ "$INSTALLED_PYTORCH_VARIANT" != "$CURRENT_PYTORCH_SETUP_FOR" ]; then
        echo "PyTorch configuration changing or first setup. Current desired: $CURRENT_PYTORCH_SETUP_FOR. Previously installed: $INSTALLED_PYTORCH_VARIANT."
        echo "Uninstalling previous torch/torchaudio (if any) and installing new version..."
        "$PIP_FROM_VENV" uninstall -y torch torchaudio || echo "Uninstall of previous torch/torchaudio skipped or failed (that's ok)."
        $TORCH_INSTALL_CMD
        echo "$CURRENT_PYTORCH_SETUP_FOR" > "$PYTORCH_VARIANT_FILE" # Mark current setup
        echo "PyTorch for $CURRENT_PYTORCH_SETUP_FOR installed."
    else
        echo "PyTorch ($INSTALLED_PYTORCH_VARIANT) already configured as desired for $CURRENT_PYTORCH_SETUP_FOR."
    fi

    echo "Ensuring openai-whisper is installed..."
    "$PIP_FROM_VENV" install --no-cache-dir openai-whisper
fi

if [ "$DESIRED_ENGINE" = "faster-whisper" ]; then
    echo "Faster-Whisper engine selected."
    echo "Ensuring faster-whisper is installed..."
    "$PIP_FROM_VENV" install --no-cache-dir "faster-whisper"
fi

# --- Set ENV VARS for Python app to find model caches ---
export WHISPER_OPENAI_CACHE_DIR="$OPENAI_WHISPER_CACHE_DIR"
export WHISPER_FASTER_CACHE_DIR="$FASTER_WHISPER_CACHE_DIR"
export XDG_CACHE_HOME="$MODEL_CACHE_ROOT" # General cache home for Hugging Face libs

echo "Python environment setup complete. Model caches configured:"
echo "  OpenAI Whisper Cache Dir: $WHISPER_OPENAI_CACHE_DIR"
echo "  Faster Whisper Cache Dir: $WHISPER_FASTER_CACHE_DIR"
echo "  XDG_CACHE_HOME: $XDG_CACHE_HOME"

# --- User/Group final adjustments (Original gosu logic) ---
# This part ensures the appuser itself exists with the right UID/GID in /etc/passwd, /etc/group
# This is more robust than just using gosu with numeric IDs if the system needs named users.
if [ "$(id -u)" = "0" ]; then # Only run if currently root
    echo "Current user is root. Adjusting user/group IDs before switching..."
    # Check if group GID needs changing or group needs to be created
    if getent group "$GNAME" &>/dev/null; then
        if [ "$(getent group $GNAME | cut -d: -f3)" != "$TARGET_PGID" ]; then
            echo "Changing group ${GNAME} GID to ${TARGET_PGID}"
            groupmod -o -g "$TARGET_PGID" $GNAME
        fi
    else
        echo "Creating group ${GNAME} with GID ${TARGET_PGID}"
        groupadd -o -g "$TARGET_PGID" $GNAME
    fi

    # Check if user UID needs changing or user needs to be created
    if getent passwd "$UNAME" &>/dev/null; then
        if [ "$(getent passwd $UNAME | cut -d: -f3)" != "$TARGET_PUID" ]; then
            echo "Changing user ${UNAME} UID to ${TARGET_PUID}"
            usermod -o -u "$TARGET_PUID" $UNAME
        fi
        # Ensure user is part of the target group
        if ! id -nG "$UNAME" | grep -qw "$GNAME"; then
            echo "Adding user $UNAME to group $GNAME"
            usermod -a -G "$GNAME" "$UNAME"
        fi
    else
        echo "Creating user ${UNAME} with UID ${TARGET_PUID} and GID ${TARGET_PGID}"
        useradd -o -u "$TARGET_PUID" -g "$TARGET_PGID" -m -s /bin/bash "$UNAME"
    fi

    # Runtime chown of app and out directories by root, as gosu will run as appuser
    echo "Ensuring ownership of /app and /out (runtime by root for appuser)..."
    chown -R "${TARGET_PUID}:${TARGET_PGID}" /app /out
fi
# --- End User/Group final adjustments ---

# --- Execute the main command ---
final_command_args=()
if [ "$1" = "python" ] && [ -n "$2" ]; then
    final_command_args=("$PYTHON_FROM_VENV" "/app/$2")
    shift 2 
    final_command_args+=("$@")
elif [ -n "$1" ]; then
    final_command_args=("$PYTHON_FROM_VENV" "/app/$1")
    shift 1
    final_command_args+=("$@")
else
    echo "Error: No command specified in CMD or arguments to entrypoint for main application."
    # Default to main.py if nothing, but CMD should provide it.
    final_command_args=("$PYTHON_FROM_VENV" "/app/main.py")
    # exit 1 # Or exit if CMD is expected to always be correct
fi

echo "Executing final command as user ${UNAME} (${TARGET_PUID}:${TARGET_PGID}): ${final_command_args[@]}"
exec /usr/local/bin/gosu "${TARGET_PUID}:${TARGET_PGID}" "${final_command_args[@]}"