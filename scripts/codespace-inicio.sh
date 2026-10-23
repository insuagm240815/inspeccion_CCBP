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

echo "Esperando a la API…"
for i in $(seq 1 60); do curl -fs http://127.0.0.1:8080/api/salud >/dev/null 2>&1 && break; sleep 3; done
curl -fs http://127.0.0.1:8080/api/salud >/dev/null || { docker compose logs --tail=50; exit 1; }

if [ ! -f datos/.usuarios-demo ]; then
  CLAVE="$(openssl rand -base64 12 | tr -d '/+=')"
  for u in "inspector:Inspector de prueba:inspector" "supervisor:Supervisor de prueba:supervisor" "admin:Admin de prueba:admin"; do
    IFS=: read -r usr nom rol <<< "$u"
    docker compose exec -T -e CLAVE_NUEVA="$CLAVE" api python -m app.usuarios crear --usuario "$usr" --nombre "$nom" --rol "$rol" || true
  done
  printf 'Usuarios de prueba: inspector, supervisor, admin\nClave (la misma para los tres): %s\n' "$CLAVE" > datos/.usuarios-demo
fi

echo
echo "════════════════════════════════════════════════════"
echo " App lista en el puerto 8080 (pestaña PORTS)."
cat datos/.usuarios-demo
echo "════════════════════════════════════════════════════"
