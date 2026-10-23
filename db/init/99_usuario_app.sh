#!/bin/bash
# Usuario de la aplicación con permisos mínimos: solo leer y escribir datos, sin tocar estructura.
set -euo pipefail
mariadb -uroot -p"${MARIADB_ROOT_PASSWORD}" <<SQL
CREATE USER IF NOT EXISTS 'inspeccion'@'%' IDENTIFIED BY '${DB_APP_PASSWORD}';
GRANT SELECT, INSERT, UPDATE, DELETE ON inspeccion_ccbp.* TO 'inspeccion'@'%';
FLUSH PRIVILEGES;
SQL
