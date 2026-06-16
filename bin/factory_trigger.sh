#!/bin/bash
# Trigger the factory after a download finishes: process any newly-downloaded
# videos (cuts -> scribe -> consensus -> segment -> DB). Serialized on the same
# lock as the backlog run, so concurrent triggers queue instead of double-processing.
# Waits for any in-progress factory to finish, then scans for whatever is new.
set -u
APPROACH="$HOME/github/approach-trainer"
DB="$HOME/github/approach-trainer/data/clips.db"
exec 9>/tmp/factory_backlog.lock
flock 9
echo "[$(date '+%F %H:%M:%S')] factory trigger fired" >> /tmp/factory_trigger.log
uv run --project "$APPROACH" approach-trainer factory "$DB" --workers 6 \
  >> /tmp/factory_trigger.log 2>&1
