SET NAMES utf8mb4;
-- Llegada detectada por GPS a cada parada y paradas que quedaron sin visitar al terminar el recorrido
ALTER TABLE itinerario_parada ADD COLUMN IF NOT EXISTS llegada DATETIME NULL AFTER marcada;
ALTER TABLE itinerario_parada ADD COLUMN IF NOT EXISTS llegada_m SMALLINT UNSIGNED NULL AFTER llegada;
ALTER TABLE itinerario_parada ADD COLUMN IF NOT EXISTS llegada_prec SMALLINT UNSIGNED NULL AFTER llegada_m;
ALTER TABLE itinerario_parada MODIFY estado ENUM('pendiente','hecha','salteada','no_visitada') NOT NULL DEFAULT 'pendiente';
