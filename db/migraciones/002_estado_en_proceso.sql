-- Agrega el estado "En proceso de resolución" a las faltas.
SET NAMES utf8mb4;
ALTER TABLE hallazgo MODIFY estado ENUM('Pendiente','Aviso verbal','Aviso por folleto','Derivado a Comisión',
  'Notificado/Intimado','En proceso de resolución','Resuelto','Verificado sin falta') NOT NULL DEFAULT 'Pendiente';
