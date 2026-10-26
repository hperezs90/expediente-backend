-- Convierte una base del sistema original (flujos fijos de Ambiente/Alimentos/Farma/SSO,
-- "reparos" y campos MARN) al modelo genérico: etapas configurables por tipo de trámite y "observaciones".
-- Conserva los datos: las fechas de los flujos viejos pasan a tramite.etapas_fechas.
-- Ejecutar UNA sola vez:  psql "$DATABASE_URL" -f migrations/001_generico.sql
BEGIN;

-- ---------- restricciones que ya no aplican (categorías fijas, máx. 3 reparos, tipos de documento) ----------
ALTER TABLE tipo_tramite DROP CONSTRAINT tipo_tramite_categoria_check;
ALTER TABLE reparo DROP CONSTRAINT reparo_numero_valido;
ALTER TABLE documento DROP CONSTRAINT documento_tipo_valido;

-- ---------- tipo_tramite ----------
ALTER TABLE tipo_tramite ALTER COLUMN categoria TYPE varchar(50);
ALTER TABLE tipo_tramite ADD COLUMN vigencia_desde varchar(10) DEFAULT 'aprobacion';
ALTER TABLE tipo_tramite ADD COLUMN etapas json DEFAULT '[]'::json;
-- En el sistema original solo SSO contaba la vigencia desde el inicio
UPDATE tipo_tramite SET vigencia_desde = CASE WHEN categoria = 'sso' THEN 'inicio' ELSE 'aprobacion' END;
-- Etapas que antes estaban fijas en el código
UPDATE tipo_tramite SET etapas = '["Paso a firma","Salida a mensajería","Ingreso"]'::json
  WHERE categoria IN ('alimentos','farma','otros');
UPDATE tipo_tramite SET etapas = '["Ingreso de instrumento","Resolución aprobatoria","Retiro de resolución","Presentación de solicitud","Retiro de licencia"]'::json
  WHERE categoria = 'ambiente' AND NOT COALESCE(es_gestion_simple, false);
UPDATE tipo_tramite SET etapas = '["Ingreso de instrumento"]'::json
  WHERE categoria = 'ambiente' AND COALESCE(es_gestion_simple, false);
ALTER TABLE tipo_tramite DROP COLUMN tipo_instrumento, DROP COLUMN es_gestion_simple;

-- ---------- tramite ----------
ALTER TABLE tramite ADD COLUMN etapas_fechas json DEFAULT '{}'::json;
UPDATE tramite t SET etapas_fechas = COALESCE((
  SELECT json_object_agg(e.nombre, e.fecha)
  FROM (VALUES
    ('Paso a firma',              t.fecha_paso_firma),
    ('Salida a mensajería',       t.fecha_salida_mensajeria),
    ('Ingreso',                   t.fecha_ingreso),
    ('Ingreso de instrumento',    t.fecha_ingreso_instrumento),
    ('Resolución aprobatoria',    t.fecha_resolucion_aprobatoria),
    ('Retiro de resolución',      t.fecha_retiro_resolucion),
    ('Presentación de solicitud', t.fecha_presentacion_solicitud),
    ('Retiro de licencia',        t.fecha_retiro_licencia)
  ) AS e(nombre, fecha)
  WHERE e.fecha IS NOT NULL
), '{}'::json);
UPDATE tramite SET resolucion_final = 'rechazado' WHERE resolucion_final = 'baja';
ALTER TABLE tramite RENAME COLUMN nombre_producto TO descripcion;
ALTER TABLE tramite
  DROP COLUMN fecha_paso_firma, DROP COLUMN fecha_salida_mensajeria, DROP COLUMN fecha_ingreso,
  DROP COLUMN nivel_impacto, DROP COLUMN fecha_ingreso_instrumento, DROP COLUMN fecha_resolucion_aprobatoria,
  DROP COLUMN fecha_retiro_resolucion, DROP COLUMN ya_construido, DROP COLUMN fecha_presentacion_solicitud,
  DROP COLUMN fecha_retiro_licencia, DROP COLUMN fecha_emision_licencia, DROP COLUMN anios_licencia;

-- ---------- reparo -> observacion ----------
ALTER TABLE reparo RENAME TO observacion;
ALTER TABLE observacion RENAME COLUMN motivo_rechazo TO motivo;
ALTER TABLE observacion RENAME COLUMN fecha_ingreso_respuesta TO fecha_respuesta;
ALTER TABLE observacion DROP COLUMN fecha_paso_firma_respuesta, DROP COLUMN fecha_salida_mensajeria_respuesta;
ALTER TABLE documento RENAME COLUMN reparo_id TO observacion_id;
ALTER TABLE alerta RENAME COLUMN reparo_id TO observacion_id;

-- ---------- documento.tipo y auditoría ----------
UPDATE documento SET tipo = CASE tipo
  WHEN 'contrasena' THEN 'ingreso' WHEN 'licencia' THEN 'resolucion' WHEN 'nota_reparo' THEN 'observacion' ELSE tipo END;
ALTER TABLE documento ADD CONSTRAINT documento_tipo_valido CHECK (tipo IN ('ingreso','resolucion','observacion','otro'));
UPDATE auditoria_tramite SET campo = regexp_replace(campo, '^reparo_', 'observacion_') WHERE campo LIKE 'reparo\_%';
UPDATE auditoria_tramite SET campo = 'descripcion' WHERE campo = 'nombre_producto';
UPDATE auditoria_tramite SET valor_nuevo = regexp_replace(valor_nuevo, '^Reparo', 'Observación') WHERE campo LIKE 'observacion\_%';

COMMIT;
