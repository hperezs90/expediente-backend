-- Versiones de documentos: cada nueva subida del mismo documento conserva las anteriores.
BEGIN;
ALTER TABLE documento ADD COLUMN version integer NOT NULL DEFAULT 1;
-- Documentos ya existentes que compartían trámite/tipo/observación: se numeran por orden de subida
UPDATE documento d SET version = n.v
FROM (
  SELECT id, row_number() OVER (
    PARTITION BY tramite_id, tipo, observacion_id ORDER BY creado_en
  ) AS v FROM documento
) n WHERE n.id = d.id;
COMMIT;
