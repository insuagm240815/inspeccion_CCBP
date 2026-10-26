-- Catálogo de EJEMPLO (códigos EJ-). Reemplazar importando el catálogo real desde la app (Catálogo → Pegar desde la planilla).
SET NAMES utf8mb4;
USE inspeccion_ccbp;
INSERT INTO rubro (nombre) VALUES ('Residuales'),('Forestación y poda'),('Cercos y frente'),('Obra');
INSERT INTO catalogo_falta (codigo,id_rubro,falta,norma) VALUES
 ('EJ-01',(SELECT id_rubro FROM rubro WHERE nombre='Residuales'),'Residuos fuera del día u horario de recolección','Completar con el reglamento'),
 ('EJ-02',(SELECT id_rubro FROM rubro WHERE nombre='Residuales'),'Reciclables mal separados o embolsados','Completar con el reglamento'),
 ('EJ-03',(SELECT id_rubro FROM rubro WHERE nombre='Forestación y poda'),'Pasto alto en el lote o la vereda','Completar con el reglamento'),
 ('EJ-04',(SELECT id_rubro FROM rubro WHERE nombre='Forestación y poda'),'Ramas sobre la calle o la vereda','Completar con el reglamento'),
 ('EJ-05',(SELECT id_rubro FROM rubro WHERE nombre='Cercos y frente'),'Cerco o frente en mal estado','Completar con el reglamento'),
 ('EJ-06',(SELECT id_rubro FROM rubro WHERE nombre='Obra'),'Obra sin cartel o sin permiso a la vista','Completar con el reglamento');
