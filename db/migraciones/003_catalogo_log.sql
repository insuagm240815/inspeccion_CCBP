-- Registro de altas, bajas y modificaciones del catálogo de faltas (quién, cuándo, qué).
SET NAMES utf8mb4;
CREATE TABLE IF NOT EXISTS catalogo_log (
  id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  fecha       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  codigo      VARCHAR(10) NOT NULL,
  accion      ENUM('alta','modificación','baja','eliminado') NOT NULL,
  detalle     VARCHAR(500),
  id_usuario  INT UNSIGNED NOT NULL,
  FOREIGN KEY (id_usuario) REFERENCES usuario(id_usuario),
  INDEX ix_catalogo_log_codigo (codigo, fecha)
) ENGINE=InnoDB;
