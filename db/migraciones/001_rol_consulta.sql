-- Agrega el rol "consulta" (solo lectura) a una base creada antes de esta versión.
-- Las instalaciones nuevas ya lo traen en 01_esquema.sql.
-- docker compose exec -T db sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" inspeccion_ccbp' < db/migraciones/001_rol_consulta.sql
SET NAMES utf8mb4;
ALTER TABLE usuario MODIFY rol ENUM('consulta','inspector','supervisor','admin') NOT NULL DEFAULT 'inspector';
