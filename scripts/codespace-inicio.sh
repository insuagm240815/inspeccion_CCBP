#!/bin/bash
# Levanta la app en un Codespace de GitHub con usuarios y datos de PRUEBA.
# No usar para producción: las claves se generan acá y la base vive dentro del Codespace.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  {
    echo "DB_ROOT_PASSWORD=$(openssl rand -hex 20)"
    echo "DB_PASSWORD=$(openssl rand -hex 20)"
    echo "WEB_BIND=127.0.0.1"
    echo "FOTOS_HOST_DIR=./datos/fotos"
  } > .env
fi
mkdir -p datos/fotos && chmod 777 datos/fotos   # el contenedor de la API escribe con un usuario sin privilegios

echo "Esperando a Docker…"
for i in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 2; done

docker compose up -d --build
docker compose restart web >/dev/null   # nginx toma la IP nueva de la API si se reconstruyó

echo "Esperando a la API…"
for i in $(seq 1 60); do curl -fs http://127.0.0.1:8080/api/salud >/dev/null 2>&1 && break; sleep 3; done
curl -fs http://127.0.0.1:8080/api/salud >/dev/null || { docker compose logs --tail=50; exit 1; }

# Migraciones (idempotentes): actualizan una base creada con una versión anterior
for f in db/migraciones/*.sql; do
  [ -f "$f" ] && docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" inspeccion_ccbp' < "$f"
done

# Usuarios de prueba (se crean los que falten, todos con la misma clave)
if [ -f datos/.usuarios-demo ]; then
  CLAVE="$(sed -n 's/^Clave[^:]*: //p' datos/.usuarios-demo)"
else
  CLAVE="$(openssl rand -base64 12 | tr -d '/+=')"
fi
for u in "inspector:Inspector de prueba:inspector" "consulta:Consulta de prueba:consulta" "supervisor:Supervisor de prueba:supervisor" "admin:Admin de prueba:admin"; do
  IFS=: read -r usr nom rol <<< "$u"
  docker compose exec -T -e CLAVE_NUEVA="$CLAVE" api python -m app.usuarios crear --usuario "$usr" --nombre "$nom" --rol "$rol" 2>/dev/null || true
done
printf 'Usuarios de prueba: inspector, consulta, supervisor, admin\nClave (la misma para todos): %s\n' "$CLAVE" > datos/.usuarios-demo

# Intentar dejar el puerto 8080 público (si no se puede, hacerlo a mano en la pestaña Puertos)
if command -v gh >/dev/null 2>&1 && [ -n "${CODESPACE_NAME:-}" ]; then
  gh codespace ports visibility 8080:public -c "$CODESPACE_NAME" >/dev/null 2>&1 \
    && echo "Puerto 8080: público." || echo "No pude hacer público el 8080: cambialo a mano en la pestaña Puertos."
fi

echo
echo "════════════════════════════════════════════════════"
echo " App lista en el puerto 8080 (pestaña PORTS)."
cat datos/.usuarios-demo
echo "════════════════════════════════════════════════════"
