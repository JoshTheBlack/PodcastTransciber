#!/bin/bash
set -e

# ... (PUID/PGID logic from your existing entrypoint.sh) ...
# Default user/group names and IDs created in Dockerfile
UNAME=appuser
GNAME=appgroup
DEFAULT_UID=99
DEFAULT_GID=100

# Take PUID and PGID from environment, defaulting to DEFAULT values
CURRENT_PUID=${PUID:-$DEFAULT_UID}
CURRENT_PGID=${PGID:-$DEFAULT_GID}

echo "Starting container with UID: ${CURRENT_PUID}, GID: ${CURRENT_PGID}"

# Check if group GID needs changing
if [ "$(getent group $GNAME | cut -d: -f3)" != "$CURRENT_PGID" ]; then
  echo "Changing group ${GNAME} GID to ${CURRENT_PGID}"
  groupmod -o -g "$CURRENT_PGID" $GNAME
fi

# Check if user UID needs changing
if [ "$(getent passwd $UNAME | cut -d: -f3)" != "$CURRENT_PUID" ]; then
  echo "Changing user ${UNAME} UID to ${CURRENT_PUID}"
  usermod -o -u "$CURRENT_PUID" $UNAME
fi

echo "Ensuring ownership of /app and /out..."
chown -R "${CURRENT_PUID}:${CURRENT_PGID}" /app /out # Assuming /out is the main output dir

# Execute the command passed into the entrypoint (the Dockerfile's CMD)
# This should now be 'python main.py' or similar if passed as CMD
echo "Executing command as ${UNAME} (${CURRENT_PUID}:${CURRENT_PGID}): $@"
exec /usr/local/bin/gosu "${CURRENT_PUID}:${CURRENT_PGID}" "$@"