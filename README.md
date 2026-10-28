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

**Tipos de faltas (ABM, solo admin):** en el menú *Tipos de faltas* se busca, se crea (*+ Nuevo tipo de falta*), se edita y se da de baja cada código.
- Un código **sin faltas cargadas** se elimina; uno **con faltas** se da de baja: deja de ofrecerse en el recorrido pero las faltas existentes conservan su descripción, y se puede reactivar.
- *Ofrecerlo al cargar faltas en el recorrido* permite ocultar un código sin darlo de baja.
- Cada alta, baja y modificación queda en *Historial de cambios de los tipos de faltas* (tabla `catalogo_log`) con usuario y fecha.
- Para la carga inicial: *Importar desde la planilla*, pegando las columnas Código, Rubro, Falta, Norma, Artículo, Penalidad, y tildando "Quitar los códigos de ejemplo".

**U.F. y Pilar:** `02_datos_base.sql` arma los grupos a partir del plano: cada lote dibujado es un Pilar. Si se carga la pestaña "U.F. y Pilar" real en la tabla `uf_pilar`, la reiterancia pasa a calcularse con los grupos reales.

## Migraciones

Los scripts de `db/init/` solo corren al crear la base. Cuando una versión nueva cambia la estructura, trae un archivo en `db/migraciones/`; se aplica así (se puede correr más de una vez sin problema):

```
for f in db/migraciones/*.sql; do
  docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" inspeccion_ccbp' < "$f"
done
```

En Codespaces lo hace solo `scripts/codespace-inicio.sh`. En Railway hay que correr cada archivo nuevo en la consola de la base (Data → Query).

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

## Usuarios

Menú **Usuarios** (solo admin): buscar, crear (*+ Nuevo usuario*, con clave generada que se muestra una sola vez), editar nombre y perfil, restablecer la clave (cierra las sesiones abiertas de esa persona) y dar de baja o reactivar.
- Un usuario **sin actividad** se elimina; uno **con actividad** se da de baja: no puede ingresar más, pero lo que cargó conserva su nombre.
- El admin no puede quitarse su propio perfil ni darse de baja, y siempre tiene que quedar al menos un admin activo.
- Los cambios de perfil y las bajas rigen en el momento, sin que la persona tenga que volver a ingresar.
- Cada persona cambia su propia clave tocando su nombre, arriba a la derecha.
- Todo queda en *Historial de cambios de usuarios* (tabla `usuario_log`). La consola (`python -m app.usuarios`) sigue disponible como respaldo.

## Reportes

Menú **Reportes**, disponible para consulta, inspector, supervisor y admin.

- Filtros: período (con atajos de 7 días, 30 días, 3 y 12 meses), sector, estado (incluye "abiertas y vencidas") y rubro.
- Indicadores: faltas detectadas, abiertas, vencidas, cerradas, días promedio hasta el cierre, visitas, U.F. con faltas y reiteradas.
- Gráficos: faltas por mes, por estado, por sector, por rubro, por inspector, tipos más frecuentes y U.F. con más faltas (cada barra muestra en naranja cuántas siguen abiertas).
- Detalle de las faltas (las 500 más recientes en pantalla; tocar una fila abre la ficha) y **Descargar Excel (CSV)** con todas las del filtro.
- **Imprimir / PDF** arma una versión para imprimir o guardar como PDF desde el navegador.

## Novedades en espacios comunes

El botón del lápiz (✎), sobre el plano, sirve para marcar problemas en calles, plazas, peatonales y otros espacios comunes. Lo ven el inspector, el supervisor y el admin.

1. Tocar ✎ y elegir **Punto** (un bache, una luminaria), **Línea** (un tramo de calle o de cerco) o **Área** (una plaza, un espacio verde).
2. Ubicarla de una de estas formas:
   - Tocando el plano. Arrastrar sigue moviendo el plano.
   - Con **📍 Mi ubicación**, que pone un punto donde está parado el inspector.
   - Con **🚶 Grabar recorrido** (solo en Línea y Área): se camina el tramo o el contorno y la app agrega un punto cada 5 m. Descarta las lecturas con precisión peor que ±30 m.

   Al tocar ✎, el GPS se enciende solo y la barra muestra la precisión. **Deshacer** borra el último punto y Esc cancela.
3. Completar el tipo, el lugar, la descripción, la fecha de revisión y las fotos.

Cada novedad guarda la latitud y la longitud del centro del dibujo y cómo se ubicó: **GPS** (con la precisión en metros) o **ubicada en el plano** (con la calibración del plano, error de ±15 m). La ficha muestra las coordenadas, un enlace **Abrir en el mapa** (Google Maps, para llegar al lugar) y **Ver en el plano**. El GPS necesita que la app se abra por HTTPS, como pasa en Codespaces, Railway y Cloudflare.

Cada novedad recibe un número M-0001 y se ve en el plano con un color según su estado: Relevado (naranja), Informado a mantenimiento (amarillo), En reparación (azul) y cerrada (verde tenue). Al tocarla se abre la ficha, con historial y fotos. Las abiertas aparecen en **Agenda → Espacios comunes**.

**Enviar por WhatsApp.** Al guardar una novedad se abre su ficha, que tiene el botón **Enviar por WhatsApp** (también disponible en cualquier ficha). Lo que se envía depende del equipo:

- **Celular:** se abre el menú de compartir del teléfono. Se elige WhatsApp y el contacto o grupo (por ejemplo, Mantenimiento). Se envían el número, el tipo, la descripción, el estado, un enlace de Google Maps con la ubicación y hasta 4 fotos.
- **PC:** se abre WhatsApp Web solo con el texto y la ubicación, porque WhatsApp no permite adjuntar fotos por enlace. Las fotos se guardan desde la ficha y se adjuntan a mano.

Lo que se manda por WhatsApp sale del servidor del country: enviar solo a contactos de trabajo.

| Acción | consulta | inspector | supervisor / admin |
|---|---|---|---|
| Ver | ✔ | ✔ | ✔ |
| Pasar a "Informado a mantenimiento" o "En reparación" | ✔ (solo las abiertas) | ✔ | ✔ |
| Crear, editar, redibujar y cerrar (Reparado o No corresponde) | | ✔ | ✔ |
| Borrar (con motivo) | | | ✔ |

## Enviar una falta por WhatsApp

La ficha de cada falta tiene el botón **WhatsApp**:
- **En el celular:** se abre el menú de compartir del teléfono. Se elige WhatsApp y el contacto o grupo, y se envían la descripción de la falta y hasta 4 fotos. La descripción incluye U.F., sector, código y tipo, norma, estado, fechas, reiterancia, observación y un enlace de Google Maps al lote.
- **En la PC:** se abre WhatsApp Web solo con el texto, porque WhatsApp no permite adjuntar fotos por enlace.

Al lado está el botón **Teams**. Las novedades de espacios comunes también tienen los dos botones:
- **En el celular:** se abre el mismo menú de compartir: se elige Teams y se envían texto, fotos y el enlace a la ficha.
- **En la PC:** se abre la ventana "Compartir en Teams" para elegir chat o canal. Lleva un texto corto, porque Teams admite hasta 200 caracteres, y el **enlace a la ficha** en la app.
  - Ese enlace pide iniciar sesión.
  - Teams no permite adjuntar fotos por enlace: están en la ficha o en la Ficha PDF.
  - Funciona en Edge o Chrome con una cuenta de Microsoft 365 (no con invitados ni cuentas gratuitas).

**Enlaces directos:** `https://…/#falta=F-0124` o `#marca=M-0003` abren esa ficha. Si no hay sesión, la abren después de iniciarla.

Lo enviado incluye datos de una U.F. y su infracción: mandarlo solo a contactos o grupos de trabajo.

## Ficha de falta en PDF

Cada falta tiene el botón **Ficha PDF**, al pie de su ficha, y lo ven todos los perfiles. Descarga `Falta F-0124 UF 2923.pdf` con el formato de Inspección técnica:

- **Encabezado:** escudo, fecha de emisión y número.
- **Barra:** U.F. (indica si está unificada), sector y número de falta.
- **En resumen:** estado, días abierta o fecha de cierre, próxima revisión y si está derivada a Comisión.
- **Falta:** código, descripción, norma, artículo, penalidad y estado.
- **Datos:** U.F., sector, rubro, visita, revisión, reiterancia y observación.
- **Fotos:** con su link "Descargar foto" (abre la foto en la app; pide iniciar sesión).
- **Historial** de movimientos y línea de **firma y aclaración**.

Las fotos van además **adjuntas al PDF** en tamaño completo: se bajan desde el panel de adjuntos del visor (el ícono del clip). Para generar el PDF, la API usa `reportlab` y `pypdf`.

## Recorrido del día

El botón **Recorrido** lo usan el inspector, el supervisor y el admin.

1. **Elegir las U.F. en el plano.** Al tocar **Recorrido** se abre la barra "Armar recorrido". Cada lote que se toca se suma (se marca en rosa); si se vuelve a tocar, se quita. Un lote unificado cuenta como una sola parada.
2. **Elegir cómo se recorre**, en la misma barra:
   - **Vehículo** o **a pie**. A pie se suman los pasos peatonales.
   - Salida desde el punto fijo o desde mi ubicación.
   - **Volver al final**, si hace falta.
3. **Orden:** lo decide la app por distancia.
4. **Calcular.** La app dibuja el recorrido numerado en el plano, con distancia y tiempo estimado (20 km/h en vehículo, 4,5 km/h a pie). Después se tocan **Empezar recorrido** y luego **Lista**.
5. **Durante el recorrido:**
   - Al cargar la visita de una U.F. del recorrido, o un cambio de estado en una novedad, la parada se tacha sola.
   - Se puede **saltear**, **marcar como hecha** o **recalcular lo que falta** desde la ubicación actual.
   - El recorrido queda guardado: planificado contra realizado. El supervisor y el admin lo pueden consultar.

**Reporte manual de cada parada:** cada parada se reporta a mano, desde la barra (para la próxima) o desde **Lista**:
- **Cargar visita:** abre el formulario, con faltas y fotos.
- **Sin novedad:** guarda una visita sin faltas.
- **Saltear.**

El GPS no marca nada automáticamente; solo se usa para "mi ubicación" (◎) y para guardar la ubicación de la visita.

**Pendiente de visita:** al **terminar el recorrido**, las paradas que no se reportaron quedan como "no visitadas". La U.F. muestra "Pendiente de visita · estaba en el itinerario planificado el dd/mm/aaaa". En el plano esos lotes se marcan con borde violeta punteado. Además:
- la leyenda muestra **Pendiente de visita** con su cantidad;
- la ficha de la U.F. avisa desde cuándo está pendiente;
- el próximo **Armar recorrido** arranca con esas U.F. ya elegidas.

La marca se borra sola cuando alguien carga una visita en esa U.F. Si un recorrido queda abierto de un día para otro, sus paradas pendientes también cuentan.

**Google Maps:** el botón **Google Maps**, en la propuesta y durante el recorrido, abre las paradas en Google Maps en el orden calculado, en vehículo o a pie. Durante el recorrido manda solo las paradas pendientes, desde la ubicación del celular.
- **Límite de paradas:** Google acepta hasta 3 paradas intermedias por enlace en el celular y 9 en la PC. Si hay más, la app ofrece el recorrido partido en tramos.
- **Camino entre paradas:** lo arma Google y puede no conocer todas las calles internas ni las manos del country.
- **Datos que salen:** solo coordenadas, sin números de U.F. ni nombres.

**Optimizar**, en la barra de armado:
- **Tiempo y combustible** (por defecto): minimiza el tiempo de manejo. A cada esquina, giro y vuelta en U le suma unos segundos (frenar y volver a acelerar es lo que más gasta en trayectos cortos), así que prefiere caminos más derechos.
- **Solo distancia:** los metros, sin tener en cuenta las maniobras.

La propuesta muestra km, minutos y una estimación de nafta: 9 L/100 km urbano, más un extra por cada parada y maniobra.

Cómo se calcula: cada parada se ancla al punto más cercano de la red de calles. Dijkstra (NetworkX) da la distancia real por calle entre paradas. El mejor orden se calcula exacto (Held-Karp) hasta 11 paradas libres; con más, se usa vecino más cercano + 2-opt.

## Calibrar plano (solo admin)

El plano de Construcciones no trae coordenadas. La calibración inicial salió de 3 puntos y tiene un error de unos 15 m. Para mejorarla:

1. **Abrir:** **Calibrar plano**. Se ven los puntos de control cargados. La línea roja de cada punto muestra cuánto erra hoy el plano en ese lugar; con zoom se ve mejor.
2. **Cargar puntos:** se toca en el plano un lugar reconocible (esquina de calle, pilar, tapa) y se carga su coordenada real de una de dos formas:
   - **Desde la oficina:** en Google Maps (vista satélite), clic derecho exactamente en el mismo lugar → clic en las coordenadas para copiarlas → pegarlas en la app. El modal tiene un enlace que abre Google Maps en esa zona.
   - **En el lugar:** **📍 Promediar mi GPS** junta lecturas durante 20 segundos (solo las de ±25 m o mejor) y las promedia.
3. **Cantidad:** cargar **15 a 20 puntos repartidos en todo el country**. La barra avisa qué zonas quedaron sin puntos.
4. **Calcular:** muestra el error estimado de cada punto, calculado *sin ese punto*, que es la precisión real esperable en esa zona. Los colores son verde (< 3 m), amarillo (3–6 m) y rojo (> 6 m). Un punto rojo muy alto suele ser un punto mal marcado: se toca y se desactiva o se borra.
5. **Corrección local (opcional):** además del ajuste general (escala, giro y deformación), corrige zona por zona. La barra compara los dos errores para saber cuál conviene.
6. **Aplicar:** la calibración nueva pasa a usarse en todos los celulares: punto azul, aviso de llegada, novedades con GPS y enlaces a Google Maps. **Volver a la inicial** deshace.

El cálculo está en `api/app/geo.py` y se repite igual en `web/app.js`.

## Red de calles (solo admin)

La red se extrajo del plano con `herramientas/red_calles`: es el eje del espacio libre entre lotes, clasificado por ancho. El botón **Red de calles** la muestra coloreada:

| Color | Tipo | Uso |
|---|---|---|
| Azul | Calle | Vehículo y a pie |
| Naranja | Paso peatonal (menos de 6,5 m) | Solo a pie |
| Gris punteado | No transitable | Nunca se usa |

- **Corregir:** tocando un tramo se cambia el tipo y la mano. Una flecha marca las manos únicas.
- **Avisos de la barra:** si la red vehicular quedó partida y qué lotes no tienen calle a menos de 40 m.
- **Mover punto de salida:** cambia la S, el punto fijo desde donde arrancan los recorridos.

Los tramos junto al golf y al club, que el plano no permitía clasificar, ya están resueltos. Los del lado del club son calles vehiculares (migración `009`). Los que bordean el golf, en los lados oeste y norte, no son calles y se quitaron de la red (migración `010`).

## Importar la planilla de Construcciones (solo admin)

El mismo botón **Importar** acepta la planilla completa de Construcciones, "Base de datos V1.0" en formato .xlsx. Se importan estas hojas:

| Hoja | Qué se hace |
|---|---|
| Catálogo | Agrega los códigos que no existen. Crea los rubros que falten. |
| Visitas | Mapea origen y contacto. Si un valor trae dos opciones ("A / B"), toma la primera válida. |
| Hallazgos | Importa con estado, revisión, cierre, foto tomada, derivado a Comisión y reiterancia. |
| Marcas | Usa la geometría del plano. Calcula latitud y longitud con la calibración del plano. |
| Historial | Importa los movimientos de faltas y marcas. |

Cómo se procesan los datos:

- **Numeración:** se conservan los números originales (V-, F-, M-) cuando están libres. Si están ocupados, se asigna uno nuevo y el historial anota "(era …)".
- **Fechas faltantes:** algunas filas migradas del Registro V14 no tienen fecha. Se estima con el primer movimiento de su historial, y si no hay ninguno, con la visita anterior. Queda anotado en la visita y se muestra en **Avisos**.
- **Versión nueva de la planilla:** lo ya importado se actualiza con los valores de la planilla (estado, revisión, cierre, observación) y solo entran las filas nuevas. Nunca duplica.
- **Revisión previa:** se hace una pasada completa y se deshace al final. Al confirmar, todo corre en una sola transacción.

No se importan Observaciones, Urgencias, Relevamientos, Regularización ni Permisos, porque la app todavía no tiene esos módulos. Tampoco las Fotos, porque son links de Google Drive, ni las Faltas borradas.

**Protección de datos:** la planilla tiene datos reales de las U.F. Cargala solo en el servidor del country (Proxmox). En Codespaces o Railway los datos quedan en servidores de terceros. Para probar ahí, usá una copia sin observaciones o con datos de ejemplo.

## Importar faltas (solo admin)

El botón **Importar** pasa a esta base las faltas que un inspector cargó en otro entorno. Sirve para armar el set de datos de una prueba funcional o para llevar a producción lo relevado en la prueba.

1. En el entorno de origen: **Reportes**, elegir el período y **Descargar Excel (CSV)**.
2. En el destino, como admin: **Importar → elegir el archivo → Revisar archivo**. Se muestra fila por fila qué se importa, qué se omite y qué tiene errores. Hasta acá no se guarda nada.
3. **Importar N faltas** confirma.

Cómo se importan las faltas:

- Cada falta recibe un número nuevo y el historial guarda el original ("era F-0004").
- Las faltas del mismo día, U.F. e inspector se agrupan en una visita.
- El inspector se busca por nombre. Si no existe en la base de destino, la falta queda a nombre del admin y se anota quién la cargó.
- Lo ya importado se omite, así que subir dos veces el mismo archivo no duplica nada.
- Los códigos tienen que existir en Tipos de faltas y las U.F. en el padrón.
- Se aceptan fechas `2026-10-26` o `26/10/2026` y separadores `;` o `,`. También sirve si el archivo se abrió y se guardó con Excel.
- No se importan fotos ni GPS, porque la planilla no los trae.

## Entorno de prueba en Railway

Para dejar la app en línea de forma permanente durante la prueba, **solo con datos ficticios** (Railway guarda los datos fuera del país).
Se arman dos servicios desde este repositorio:

| Servicio | Origen | Configuración |
|---|---|---|
| **db** | GitHub repo, *Root Directory* `/db` (usa `db/Dockerfile`) | Volumen en `/var/lib/mysql`. Variables: `MARIADB_ROOT_PASSWORD`, `DB_APP_PASSWORD` (claves largas) |
| **app** | GitHub repo, raíz del repo | Variable `RAILWAY_DOCKERFILE_PATH=Dockerfile.railway`. Volumen en `/data/fotos`. Dominio público en *Settings → Networking → Generate Domain* |

Variables del servicio **app**:

```
RAILWAY_DOCKERFILE_PATH=Dockerfile.railway
RAILWAY_RUN_UID=0
DB_HOST=${{db.RAILWAY_PRIVATE_DOMAIN}}
DB_PORT=3306
DB_USER=inspeccion
DB_PASSWORD=${{db.DB_APP_PASSWORD}}
DB_NAME=inspeccion_ccbp
COOKIE_SECURE=1
ADMIN_USUARIO=admin
ADMIN_CLAVE=<clave del admin, 10+ caracteres>
DEMO_CLAVE=<opcional: crea inspector, consulta y supervisor de prueba con esta clave>
```

`ADMIN_*` y `DEMO_CLAVE` solo crean usuarios que no existan; nunca cambian una clave existente. Una vez creados, se pueden borrar esas variables.
En este modo la API sirve también la web (sin nginx) y agrega las mismas cabeceras de seguridad.

## Pendiente (próximas etapas)

- Observaciones preventivas, urgencias y regularización. El modelo ya está en el DER.
- Funcionamiento sin señal: guardar en el celular y enviar al recuperar conexión.
- Exportar a planilla y armar el PDF de notificación.
- Migrar los datos actuales de la planilla de Construcciones.
