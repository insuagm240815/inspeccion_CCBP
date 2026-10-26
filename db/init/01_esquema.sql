-- Base de Inspección CCBP — esquema MariaDB (núcleo del DER + seguridad y GPS)
-- Se ejecuta solo la primera vez que arranca el contenedor de MariaDB (volumen vacío).
-- Las tablas de observaciones, marcas, relevamientos, urgencias y regularización del DER
-- se suman en la próxima etapa.

SET NAMES utf8mb4;
CREATE DATABASE IF NOT EXISTS inspeccion_ccbp CHARACTER SET utf8mb4 COLLATE utf8mb4_spanish_ci;
USE inspeccion_ccbp;

-- ───────── Territorio y catálogo ─────────
CREATE TABLE sector (
  id_sector  TINYINT UNSIGNED PRIMARY KEY,
  nombre     VARCHAR(20) NOT NULL UNIQUE,
  uf_desde   SMALLINT UNSIGNED NOT NULL,
  uf_hasta   SMALLINT UNSIGNED NOT NULL,
  CHECK (uf_desde <= uf_hasta)
) ENGINE=InnoDB;

CREATE TABLE unidad_funcional (
  nro_uf     SMALLINT UNSIGNED PRIMARY KEY,
  id_sector  TINYINT UNSIGNED NOT NULL,
  FOREIGN KEY (id_sector) REFERENCES sector(id_sector)
) ENGINE=InnoDB;

CREATE TABLE pilar (
  nro_pilar  SMALLINT UNSIGNED PRIMARY KEY
) ENGINE=InnoDB;

CREATE TABLE uf_pilar (
  nro_uf     SMALLINT UNSIGNED,
  nro_pilar  SMALLINT UNSIGNED,
  PRIMARY KEY (nro_uf, nro_pilar),
  INDEX ix_uf_pilar_pilar (nro_pilar),
  FOREIGN KEY (nro_uf)    REFERENCES unidad_funcional(nro_uf),
  FOREIGN KEY (nro_pilar) REFERENCES pilar(nro_pilar)
) ENGINE=InnoDB;

CREATE TABLE rubro (
  id_rubro   SMALLINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre     VARCHAR(80) NOT NULL UNIQUE
) ENGINE=InnoDB;

CREATE TABLE catalogo_falta (
  codigo             VARCHAR(10) PRIMARY KEY,
  id_rubro           SMALLINT UNSIGNED NOT NULL,
  falta              VARCHAR(250) NOT NULL,
  que_observar       TEXT,
  norma              VARCHAR(150),
  articulo           VARCHAR(40),
  penalidad          VARCHAR(150),
  visible_recorrido  BOOLEAN NOT NULL DEFAULT TRUE,
  activo             BOOLEAN NOT NULL DEFAULT TRUE,
  FOREIGN KEY (id_rubro) REFERENCES rubro(id_rubro)
) ENGINE=InnoDB;

-- ───────── Seguridad ─────────
CREATE TABLE usuario (
  id_usuario   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  usuario      VARCHAR(40) NOT NULL UNIQUE,
  nombre       VARCHAR(80) NOT NULL,
  rol          ENUM('consulta','inspector','supervisor','admin') NOT NULL DEFAULT 'inspector',
  clave_hash   VARCHAR(255) NOT NULL,                     -- argon2id
  activo       BOOLEAN NOT NULL DEFAULT TRUE,
  creado       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE sesion (
  token_hash   CHAR(64) PRIMARY KEY,                      -- SHA-256 del token; el token nunca se guarda
  id_usuario   INT UNSIGNED NOT NULL,
  creada       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expira       DATETIME NOT NULL,
  ip           VARCHAR(45),
  FOREIGN KEY (id_usuario) REFERENCES usuario(id_usuario) ON DELETE CASCADE,
  INDEX ix_sesion_expira (expira)
) ENGINE=InnoDB;

CREATE TABLE acceso_log (
  id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  fecha        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  usuario      VARCHAR(40),
  ip           VARCHAR(45),
  resultado    ENUM('ok','clave','bloqueado','inactivo') NOT NULL
) ENGINE=InnoDB;

CREATE TABLE catalogo_log (                                -- ABM del catálogo: quién, cuándo, qué
  id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  fecha       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  codigo      VARCHAR(10) NOT NULL,
  accion      ENUM('alta','modificación','baja','eliminado') NOT NULL,
  detalle     VARCHAR(500),
  id_usuario  INT UNSIGNED NOT NULL,
  FOREIGN KEY (id_usuario) REFERENCES usuario(id_usuario),
  INDEX ix_catalogo_log_codigo (codigo, fecha)
) ENGINE=InnoDB;

CREATE TABLE secuencia (                                  -- numeración V-, F-, P- con bloqueo de fila
  prefijo  VARCHAR(2) PRIMARY KEY,
  ultimo   INT UNSIGNED NOT NULL DEFAULT 0
) ENGINE=InnoDB;
INSERT INTO secuencia VALUES ('V',0),('F',0),('P',0);

-- ───────── Inspección ─────────
CREATE TABLE visita (
  nro_visita   VARCHAR(10) PRIMARY KEY,                   -- V-0001
  fecha        DATE NOT NULL,
  nro_uf       SMALLINT UNSIGNED NOT NULL,
  origen       ENUM('Recorrido de inspección','Reclamo de vecino',
                    'Reclamo del servicio de recolección','Revisión de caso') NOT NULL,
  contacto     ENUM('Hablé con el residente','No había nadie',
                    'No había nadie, dejé aviso escrito',
                    'Hablé con personal de poda, pasto, obra o limpieza',
                    'Pendiente de visita') NULL,
  observacion  TEXT,
  lat          DECIMAL(9,6) NULL,                         -- posición del celular al cargar
  lon          DECIMAL(9,6) NULL,
  precision_m  SMALLINT UNSIGNED NULL,
  id_usuario   INT UNSIGNED NOT NULL,
  creado       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (nro_uf)     REFERENCES unidad_funcional(nro_uf),
  FOREIGN KEY (id_usuario) REFERENCES usuario(id_usuario),
  INDEX ix_visita_uf_fecha (nro_uf, fecha)
) ENGINE=InnoDB;

CREATE TABLE registro (                                    -- supertipo F-, O-, M-, R-
  nro_registro VARCHAR(10) PRIMARY KEY,
  tipo         ENUM('F','O','M','R') NOT NULL,
  creado       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE hallazgo (
  nro_hallazgo       VARCHAR(10) PRIMARY KEY,
  nro_visita         VARCHAR(10) NOT NULL,
  codigo             VARCHAR(10) NOT NULL,
  fecha              DATE NOT NULL,
  estado             ENUM('Pendiente','Aviso verbal','Aviso por folleto','Derivado a Comisión',
                          'Notificado/Intimado','En proceso de resolución','Resuelto','Verificado sin falta') NOT NULL DEFAULT 'Pendiente',
  fecha_revision     DATE NULL,
  foto_tomada        BOOLEAN NOT NULL DEFAULT FALSE,
  derivado_comision  BOOLEAN NOT NULL DEFAULT FALSE,
  observacion        TEXT,
  reiterancia        SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  fecha_cierre       DATE NULL,
  id_usuario         INT UNSIGNED NOT NULL,
  FOREIGN KEY (nro_hallazgo) REFERENCES registro(nro_registro) ON DELETE CASCADE,
  FOREIGN KEY (nro_visita)   REFERENCES visita(nro_visita),
  FOREIGN KEY (codigo)       REFERENCES catalogo_falta(codigo),
  FOREIGN KEY (id_usuario)   REFERENCES usuario(id_usuario),
  INDEX ix_hallazgo_estado_rev (estado, fecha_revision),
  INDEX ix_hallazgo_codigo (codigo)
) ENGINE=InnoDB;

CREATE TABLE historial (
  id_historial  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nro_registro  VARCHAR(10) NOT NULL,
  nro_visita    VARCHAR(10) NULL,
  fecha         DATE NOT NULL,
  cambio        VARCHAR(500) NOT NULL,
  nota          TEXT,
  id_usuario    INT UNSIGNED NOT NULL,
  creado        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (nro_registro) REFERENCES registro(nro_registro) ON DELETE CASCADE,
  FOREIGN KEY (nro_visita)   REFERENCES visita(nro_visita),
  FOREIGN KEY (id_usuario)   REFERENCES usuario(id_usuario),
  INDEX ix_historial_reg (nro_registro, creado)
) ENGINE=InnoDB;

CREATE TABLE foto (
  nro_foto      VARCHAR(10) PRIMARY KEY,                   -- P-0001
  nro_registro  VARCHAR(10) NULL,
  nro_visita    VARCHAR(10) NULL,
  fecha         DATE NOT NULL,
  momento       ENUM('Antes','Después','Seguimiento','Agregada','Visita',
                     'Observación','Relevamiento') NOT NULL,
  archivo       VARCHAR(200) NOT NULL,                     -- ruta relativa dentro del volumen de fotos
  bytes         INT UNSIGNED NOT NULL,
  id_usuario    INT UNSIGNED NOT NULL,
  creado        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (nro_registro) REFERENCES registro(nro_registro) ON DELETE CASCADE,
  FOREIGN KEY (nro_visita)   REFERENCES visita(nro_visita),
  FOREIGN KEY (id_usuario)   REFERENCES usuario(id_usuario),
  CHECK (nro_registro IS NOT NULL OR nro_visita IS NOT NULL)
) ENGINE=InnoDB;

CREATE TABLE registro_borrado (                            -- bitácora, sin FK al registro a propósito
  id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  borrado_el        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  nro_registro      VARCHAR(10) NOT NULL,
  nro_uf            SMALLINT UNSIGNED NULL,
  descripcion       VARCHAR(300),
  estado            VARCHAR(60),
  fecha             DATE NULL,
  observacion       TEXT,
  motivo            TEXT NOT NULL,
  fotos_eliminadas  SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  id_usuario        INT UNSIGNED NOT NULL,
  FOREIGN KEY (id_usuario) REFERENCES usuario(id_usuario)
) ENGINE=InnoDB;

-- ───────── Vista de consulta ─────────
CREATE VIEW v_faltas_abiertas AS
SELECT h.nro_hallazgo, v.nro_uf, s.nombre AS sector, r.nombre AS rubro,
       CONCAT(c.codigo,' ',c.falta) AS tipo_de_falta, h.estado, h.fecha, h.fecha_revision,
       u.nombre AS cargado_por
FROM hallazgo h
JOIN visita v            ON v.nro_visita = h.nro_visita
JOIN unidad_funcional uf ON uf.nro_uf = v.nro_uf
JOIN sector s            ON s.id_sector = uf.id_sector
JOIN catalogo_falta c    ON c.codigo = h.codigo
JOIN rubro r             ON r.id_rubro = c.id_rubro
JOIN usuario u           ON u.id_usuario = h.id_usuario
WHERE h.estado NOT IN ('Resuelto','Verificado sin falta');
