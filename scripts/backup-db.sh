#!/usr/bin/env sh
set -eu

SOURCE_DB="${1:-/data/spot_bot.db}"
BACKUP_DIR="${2:-/data/backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DB="${BACKUP_DIR}/spot_bot-${TIMESTAMP}.db"

mkdir -p "$BACKUP_DIR"

python - "$SOURCE_DB" "$BACKUP_DB" <<'PY'
import sqlite3
import sys

source_path, backup_path = sys.argv[1], sys.argv[2]
source = sqlite3.connect(source_path)
backup = sqlite3.connect(backup_path)
source.backup(backup)
backup.close()
source.close()
print(backup_path)
PY
