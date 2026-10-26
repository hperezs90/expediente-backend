-- Renovaciones: un trámite puede ser la renovación (o el siguiente periodo) de otro.
BEGIN;
ALTER TABLE tramite ADD COLUMN renueva_a_id uuid REFERENCES tramite(id) ON DELETE SET NULL;
CREATE INDEX ix_tramite_renueva_a_id ON tramite(renueva_a_id);
COMMIT;
