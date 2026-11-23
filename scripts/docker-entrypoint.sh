#!/bin/sh
# Container entrypoint: make the data folder writable, then run as `orca`.
#
# Fly volumes, Railway volumes and Render disks mount root-owned over /data,
# hiding the image's chown, so the server (which runs as the unprivileged
# `orca` user) couldn't create its SQLite database there. Starting as root,
# this hands the folder to `orca` when needed and then drops privileges for
# good. Where the platform already runs the container as a non-root user,
# it starts the server directly.
set -e

DATA_DIR="${ORCA_DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    if [ "$(stat -c %U "$DATA_DIR")" != "orca" ]; then
        chown -R orca:orca "$DATA_DIR"
    fi
    exec setpriv --reuid=orca --regid=orca --init-groups "$@"
fi

exec "$@"
