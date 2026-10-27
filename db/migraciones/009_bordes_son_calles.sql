SET NAMES utf8mb4;
-- Confirmado en el terreno: los tramos junto al golf y al club son calles de tránsito vehicular.
-- No toca los que el admin ya corrigió a mano desde el editor.
UPDATE red_tramo SET tipo='calle', revisado=TRUE WHERE tipo='borde' AND modificado IS NULL;
