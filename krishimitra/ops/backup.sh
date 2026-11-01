#!/usr/bin/env bash
# Nightly: ./ops/backup.sh   (cron it). Keeps 14 days. Test a restore before you rely on it.
set -euo pipefail
OUT=${BACKUP_DIR:-./backups}; mkdir -p "$OUT"
docker compose exec -T postgres pg_dump -U krishimitra krishimitra | gzip > "$OUT/db-$(date +%F).sql.gz"
docker run --rm -v krishimitra_uploads:/d -v "$(cd "$OUT" && pwd)":/o alpine tar czf "/o/uploads-$(date +%F).tgz" -C /d .
find "$OUT" -type f -mtime +14 -delete
