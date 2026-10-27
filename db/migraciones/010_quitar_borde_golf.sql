SET NAMES utf8mb4;
-- Los tramos que bordean el golf (lado oeste y norte) no son calles: se quitan de la red.
-- El 51 es un pedacito que quedaba suelto entre ellos. No toca los que el admin haya corregido a mano.
DELETE FROM red_tramo WHERE id_tramo IN (33,34,50,51,52,86,153,154,156) AND modificado IS NULL;
