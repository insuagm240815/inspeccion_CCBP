-- Novedades en espacios comunes (calles, peatonales, plazas…): punto, línea o área dibujada en el plano.
SET NAMES utf8mb4;
INSERT IGNORE INTO secuencia VALUES ('M',0);
CREATE TABLE IF NOT EXISTS marca (
  nro_marca       VARCHAR(10) PRIMARY KEY,                    -- M-0001 (subtipo de registro)
  fecha           DATE NOT NULL,
  tipo            VARCHAR(60) NOT NULL,                       -- categoría: bache, luminaria, arbolado…
  descripcion     VARCHAR(500) NOT NULL,
  forma           ENUM('Punto','Línea','Área') NOT NULL,
  geometria       JSON NOT NULL,                              -- [[x,y],…] en coordenadas del plano
  lugar           ENUM('Calle','Peatonal','Plaza','Espacio verde','Club / deportes','Perímetro','Otro') NOT NULL DEFAULT 'Calle',
  id_sector       TINYINT UNSIGNED NULL,
  estado          ENUM('Relevado','Informado a mantenimiento','En reparación','Reparado','No corresponde') NOT NULL DEFAULT 'Relevado',
  fecha_revision  DATE NULL,
  observacion     TEXT,
  fecha_cierre    DATE NULL,
  lat             DECIMAL(9,6) NULL,
  lon             DECIMAL(9,6) NULL,
  id_usuario      INT UNSIGNED NOT NULL,
  creado          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (nro_marca)  REFERENCES registro(nro_registro) ON DELETE CASCADE,
  FOREIGN KEY (id_sector)  REFERENCES sector(id_sector),
  FOREIGN KEY (id_usuario) REFERENCES usuario(id_usuario),
  CHECK (JSON_VALID(geometria)),
  INDEX ix_marca_estado (estado, fecha_revision)
) ENGINE=InnoDB;
