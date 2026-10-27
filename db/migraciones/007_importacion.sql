SET NAMES utf8mb4;
-- Importación de faltas desde la planilla CSV de Reportes (solo admin)
CREATE TABLE IF NOT EXISTS importacion (
  id_importacion INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  archivo        VARCHAR(120) NOT NULL,
  filas          INT UNSIGNED NOT NULL,
  creadas        INT UNSIGNED NOT NULL,
  omitidas       INT UNSIGNED NOT NULL,
  errores        INT UNSIGNED NOT NULL,
  id_usuario     INT UNSIGNED NOT NULL,
  creado         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (id_usuario) REFERENCES usuario(id_usuario)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS importacion_item (
  clave          CHAR(64) PRIMARY KEY,                 -- sha256(n° origen | fecha | U.F. | código): evita importar dos veces la misma fila
  id_importacion INT UNSIGNED NOT NULL,
  nro_origen     VARCHAR(10) NOT NULL,
  nro_registro   VARCHAR(10) NOT NULL,
  FOREIGN KEY (id_importacion) REFERENCES importacion(id_importacion) ON DELETE CASCADE
) ENGINE=InnoDB;
