SET NAMES utf8mb4;
USE inspeccion_ccbp;
-- Puntos de control para georreferenciar el plano (Calibrar plano, solo admin)
CREATE TABLE IF NOT EXISTS calib_punto (
  id_punto   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  x          DECIMAL(7,1) NOT NULL,                -- coordenadas en el plano
  y          DECIMAL(7,1) NOT NULL,
  lat        DECIMAL(10,7) NOT NULL,
  lon        DECIMAL(10,7) NOT NULL,
  origen     ENUM('mapa','gps') NOT NULL,          -- copiado de Google Maps o GPS promediado en el lugar
  prec_m     SMALLINT UNSIGNED NULL,
  nota       VARCHAR(120) NULL,
  activo     BOOLEAN NOT NULL DEFAULT TRUE,
  id_usuario INT UNSIGNED NOT NULL,
  creado     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (id_usuario) REFERENCES usuario(id_usuario)
) ENGINE=InnoDB;
