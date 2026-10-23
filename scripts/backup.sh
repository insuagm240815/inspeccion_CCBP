#!/bin/bash
# Backup diario: base de datos + fotos. Programar en cron de la VM, por ejemplo:
#   15 2 * * *  /opt/inspeccion-ccbp/scripts/backup.sh /mnt/synology/backups/inspeccion
set -euo pipefail
DEST="${1:?Indicá la carpeta destino (por ejemplo un share del Synology)}"
cd "$(dirname "$0")/.."
source .env
F=$(date +%Y-%m-%d_%H%M)
mkdir -p "$DEST/db" "$DEST/fotos"
docker compose exec -T db mariadb-dump -uroot -p"$DB_ROOT_PASSWORD" --single-transaction --routines inspeccion_ccbp | gzip > "$DEST/db/inspeccion_$F.sql.gz"
rsync -a "${FOTOS_HOST_DIR:-./datos/fotos}/" "$DEST/fotos/"
find "$DEST/db" -name 'inspeccion_*.sql.gz' -mtime +30 -delete
echo "Backup OK: $DEST/db/inspeccion_$F.sql.gz"
