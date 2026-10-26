-- Registro del ABM de usuarios: altas, bajas, cambios de perfil y de clave (quién lo hizo y cuándo).
SET NAMES utf8mb4;
CREATE TABLE IF NOT EXISTS usuario_log (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  fecha           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  id_usuario_obj  INT UNSIGNED NULL,
  usuario         VARCHAR(40) NOT NULL,
  accion          ENUM('alta','modificación','baja','reactivación','clave','eliminado') NOT NULL,
  detalle         VARCHAR(300),
  id_actor        INT UNSIGNED NOT NULL,
  FOREIGN KEY (id_actor) REFERENCES usuario(id_usuario),
  INDEX ix_usuario_log (usuario, fecha)
) ENGINE=InnoDB;
