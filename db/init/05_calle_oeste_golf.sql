SET NAMES utf8mb4;
USE inspeccion_ccbp;
-- La calle que corre junto al lado oeste del golf sí es transitable: se vuelve a unir con la calle del sur (tramo 154).
INSERT IGNORE INTO red_tramo (id_tramo, nodo_a, nodo_b, tipo, geometria, largo_m, revisado)
VALUES (154,116,73,'calle','[[1321,2517],[1321,2672],[1330,2680]]',67.0,TRUE);
