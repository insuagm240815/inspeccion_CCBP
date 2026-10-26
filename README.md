# Inspección CCBP

Aplicación web para la inspección técnica del country: plano de lotes, visitas, faltas, seguimiento, fotos y GPS. Todos los datos quedan en la infraestructura del CCBP.

## Arquitectura

```
Celular / PC ── HTTPS ──► Cloudflare Tunnel (o FortiGate) ──► VM en Proxmox
                                                              ├─ web  (nginx: app + cabeceras de seguridad)
                                                              ├─ api  (Python FastAPI, un proceso)
                                                              ├─ db   (MariaDB 11.4, sin puerto expuesto)
                                                              └─ fotos (disco de la VM o NFS del Synology)
```

| Pieza | Qué hace |
|---|---|
| `web/` | La app: plano, formularios, GPS. Sin dependencias externas salvo la tipografía. |
| `api/` | Login, permisos, lectura y escritura en MariaDB, fotos, aviso en vivo (Server-Sent Events). |
| `db/init/` | Esquema del DER (núcleo), datos base del plano, catálogo de ejemplo y usuario de la app con permisos mínimos. |
| `nginx/` | Proxy hacia la API y política de seguridad del navegador (CSP, HSTS, etc.). |
| `scripts/backup.sh` | Volcado diario de la base y copia de las fotos. |

## Protección de datos

- **Datos en casa.** Base y fotos en la VM del CCBP. Ningún servicio de terceros almacena información.
- **Acceso con usuario y clave.** Clave con argon2id; sesión en cookie `HttpOnly`, `Secure`, `SameSite=Strict`, que vence a las 12 h. Se bloquea por 15 minutos tras 8 intentos fallidos. Cada ingreso queda en `acceso_log`.
- **Roles.**

  | Rol | Puede |
  |---|---|
  | consulta | ver todo (plano, fichas, historial, fotos, agenda) y **gestionar faltas abiertas**: marcarlas como *Notificado/Intimado* o *En proceso de resolución*, con nota y fecha de revisión. No carga visitas, no sube fotos, no cierra faltas |
  | inspector | cargar visitas, cambiar estados, reprogramar |
  | supervisor | además, borrar faltas (con motivo obligatorio) |
  | admin | todo: es el superusuario (incluye cargar el catálogo) |

- **Auditoría.** Cada visita, falta, cambio de estado, foto y borrado guarda quién lo hizo. Los borrados dejan constancia en `registro_borrado`, y las fotos de lo borrado pasan a `_papelera` en lugar de eliminarse.
- **Fotos privadas.** Solo se ven con sesión iniciada (no hay links públicos). Se re-codifican al subirlas, lo que elimina los metadatos EXIF (incluida la ubicación del celular) y descarta archivos que no sean imágenes.
- **Ubicación.** Se guarda la posición del inspector solo al momento de cargar una visita, nunca un seguimiento continuo.
- **Base con permisos mínimos.** La app usa un usuario de MariaDB que solo puede leer y escribir datos, no cambiar la estructura. MariaDB no expone puertos fuera de Docker.

Corresponde informar a los inspectores que la app registra la ubicación al cargar cada visita, y definir cuánto tiempo se conservan fotos y registros (Ley 25.326).

## Instalación en Proxmox

1. Crear una VM Debian 12 (2 vCPU, 4 GB RAM, 40 GB de disco; para fotos, sumar disco o montar un share NFS del Synology).
2. Instalar Docker: `curl -fsSL https://get.docker.com | sh`
3. Copiar esta carpeta a `/opt/inspeccion-ccbp` y entrar a ella.
4. `cp .env.example .env` y completar `DB_ROOT_PASSWORD` y `DB_PASSWORD` con claves largas (por ejemplo `openssl rand -base64 30`).
5. `docker compose up -d --build`
6. Crear el primer administrador:
   ```
   docker compose exec api python -m app.usuarios crear --usuario martin --nombre "Martín" --rol admin
   ```
7. Probar desde la VM: `curl http://127.0.0.1:8080/api/salud` → `{"ok":true}`

Los scripts de `db/init/` corren solo la primera vez (con el volumen de la base vacío).

## Acceso desde la calle

El GPS del navegador **solo funciona por HTTPS**, así que la app tiene que publicarse con certificado válido.

**Opción recomendada: Cloudflare Tunnel + Cloudflare Access.** No abre puertos en el FortiGate: la VM sale hacia Cloudflare.

1. En Cloudflare Zero Trust, crear un túnel y apuntar el hostname (por ejemplo `inspeccion.ccbp.com.ar`) a `http://web:80`.
2. Copiar el token en `CLOUDFLARE_TUNNEL_TOKEN` del `.env` y levantar con `docker compose --profile tunel up -d`.
3. En Access, crear una aplicación para ese hostname con política "emails de la lista de inspectores" (código por mail o cuenta de Google/Microsoft). Así, antes de llegar a la pantalla de login de la app, Cloudflare ya filtró quién puede entrar.

El tráfico pasa por Cloudflare cifrado, pero los datos no se almacenan ahí.

**Alternativa: VIP en el FortiGate.**

1. Poner la VM en una DMZ, sin ruta hacia la LAN de servidores ni hacia AD.
2. Publicar el 443 con un proxy TLS (por ejemplo Caddy o el propio FortiGate con certificado).
3. `WEB_BIND` con la IP de la VM.
4. Aplicar perfil IPS y restricción geográfica a Argentina en la política.

**Solo red interna o VPN:** `WEB_BIND` con la IP de la VM y un certificado interno. Sin HTTPS válido el GPS no anda.

## Operación diaria

| Tarea | Comando |
|---|---|
| Alta de usuario | `docker compose exec api python -m app.usuarios crear --usuario mperez --nombre "María Pérez" --rol inspector` |
| Cambio de clave | `docker compose exec api python -m app.usuarios clave --usuario mperez` |
| Baja (cierra sus sesiones) | `docker compose exec api python -m app.usuarios baja --usuario mperez` |
| Usuario de solo lectura | `docker compose exec api python -m app.usuarios crear --usuario jefe --nombre "Jefe de Construcciones" --rol consulta` |
| Listar usuarios | `docker compose exec api python -m app.usuarios listar` |
| Ver logs | `docker compose logs -f api` |
| Actualizar la app | `git pull`, `docker compose up -d --build` y aplicar las migraciones nuevas de `db/migraciones/` (ver abajo) |

**Catálogo:** un admin entra en Catálogo, pega las columnas Código, Rubro, Falta, Norma, Artículo, Penalidad copiadas de la planilla y tilda "Quitar los códigos de ejemplo".

**U.F. y Pilar:** `02_datos_base.sql` arma los grupos a partir del plano: cada lote dibujado es un Pilar. Si se carga la pestaña "U.F. y Pilar" real en la tabla `uf_pilar`, la reiterancia pasa a calcularse con los grupos reales.

## Migraciones

Los scripts de `db/init/` solo corren al crear la base. Cuando una versión nueva cambia la estructura, trae un archivo en `db/migraciones/`; se aplica así (se puede correr más de una vez sin problema):

```
for f in db/migraciones/*.sql; do
  docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" inspeccion_ccbp' < "$f"
done
```

En Codespaces lo hace solo `scripts/codespace-inicio.sh`.

## Backup

```
# cron de la VM, todos los días 02:15, a un share del Synology
15 2 * * *  /opt/inspeccion-ccbp/scripts/backup.sh /mnt/synology/backups/inspeccion
```

El script guarda 30 días de volcados de la base y sincroniza las fotos. Para restaurar:

```
gunzip -c inspeccion_FECHA.sql.gz | docker compose exec -T db mariadb -uroot -p"$DB_ROOT_PASSWORD" inspeccion_ccbp
```

Hay que probar la restauración al menos una vez antes de salir a producción.

## Trabajo en GitHub

1. Crear un repositorio **privado** (por ejemplo `ccbp/inspeccion`) y subir esta carpeta:
   ```
   git remote add origin git@github.com:ccbp/inspeccion.git
   git push -u origin main
   ```
2. Ramas: `main` es lo aprobado para producción; cada cambio se trabaja en una rama (`feature/...`) y entra por *pull request*.
3. Cada push corre las pruebas automáticas (`.github/workflows/ci.yml`):
   - API contra una MariaDB real: login, permisos, visita con fotos y GPS, cambio de estado, reprogramación, borrado, catálogo;
   - sintaxis del frontend;
   - construcción de la imagen Docker.
4. En *Settings → Branches* proteger `main`: exigir que el check "Pruebas" pase y al menos una aprobación antes de fusionar.
5. Nunca subir `.env` (ya está en `.gitignore`), fotos ni volcados de la base.

Pruebas locales, desde `api/` con una MariaDB de desarrollo:

```
pip install -r requirements.txt -r requirements-dev.txt
DB_HOST=127.0.0.1 DB_USER=inspeccion DB_PASSWORD=... FOTOS_DIR=/tmp/fotos COOKIE_SECURE=0 pytest -q
```

## Probar en línea con GitHub Codespaces

Levanta la app completa (MariaDB + API + nginx) en una máquina de GitHub, con dirección HTTPS propia. Usar **solo con datos de prueba**.

1. En el repo: *Code → Codespaces → Create codespace on main*.
2. Esperar 3 a 5 minutos. El script `scripts/codespace-inicio.sh` arma todo, crea los usuarios `inspector`, `supervisor` y `admin`, y muestra la clave en la terminal. Se puede volver a ver con `cat datos/.usuarios-demo`.
3. En la pestaña **PORTS**, abrir el puerto 8080 (ícono del globo).
   - Visibilidad *Private* (por defecto): solo entra quien inicie sesión con tu cuenta de GitHub.
   - Para que lo prueben otros desde el celular: clic derecho → *Port visibility → Public*. La app igual pide usuario y clave.
4. El GPS funciona porque la dirección es HTTPS.

El Codespace se apaga solo tras 30 minutos sin uso. Al volver a abrirlo, los datos siguen ahí. Si se borra el Codespace, se pierden los datos de prueba.

## Pendiente (próximas etapas)

- Observaciones preventivas, marcas en áreas comunes, urgencias y regularización. El modelo ya está en el DER.
- Funcionamiento sin señal: guardar en el celular y enviar al recuperar conexión.
- Exportar a planilla y armar el PDF de notificación.
- Migrar los datos actuales de la planilla de Construcciones.
