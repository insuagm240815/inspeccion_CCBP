SET NAMES utf8mb4;
-- Geolocalización de las novedades en espacios comunes
ALTER TABLE marca ADD COLUMN IF NOT EXISTS precision_m SMALLINT UNSIGNED NULL AFTER lon;
ALTER TABLE marca ADD COLUMN IF NOT EXISTS ubicacion ENUM('Plano','GPS') NOT NULL DEFAULT 'Plano' AFTER precision_m;
