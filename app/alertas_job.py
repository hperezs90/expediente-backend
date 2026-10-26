import os

from datetime import date, datetime

from sqlalchemy.orm import Session, joinedload

from . import config, models
from .database import SessionLocal
from .emailing import enviar_correo

# Umbrales de alerta (configurables en config.py / variables de entorno), de mayor a menor.
# Cada uno define el TECHO de una banda: banda(90) = faltan entre 61 y 90 días; banda(60) = entre 31 y 60; etc.
# Es por rango, no por fecha exacta: si el job no corre un día puntual, la alerta no se pierde,
# solo se manda un poco después dentro de la misma banda.
UMBRALES_TRAMITE = config.UMBRALES_VENCIMIENTO
UMBRALES_OBSERVACION = config.UMBRALES_OBSERVACION

# Todas las alertas van a un único correo (no se reparten por gestor asignado),
# porque es el que revisa todo el equipo.
CORREO_UNICO_ALERTAS = os.getenv("CORREO_UNICO_ALERTAS", "")


def banda_para(dias_restantes: int, umbrales: list) -> int | None:
    """Devuelve a qué umbral pertenece dias_restantes, o None si está fuera de rango."""
    if dias_restantes is None or dias_restantes < 0:
        return None
    umbrales_ordenados = sorted(umbrales, reverse=True)
    for idx, techo in enumerate(umbrales_ordenados):
        piso = umbrales_ordenados[idx + 1] + 1 if idx + 1 < len(umbrales_ordenados) else 0
        if piso <= dias_restantes <= techo:
            return techo
    return None


def destinatarios_para_empresa(db: Session, empresa_id) -> list:
    """Todas las alertas van a un único correo fijo (no se reparten por gestor asignado)."""
    if CORREO_UNICO_ALERTAS:
        return [CORREO_UNICO_ALERTAS]

    # Respaldo por si no se configuró la variable de entorno: manda a los admins.
    admins = db.query(models.Usuario.email).filter(models.Usuario.rol == "admin").filter(models.Usuario.activo.is_(True)).all()
    return [a[0] for a in admins]


def ya_fue_enviada(db: Session, tramite_id, banda: int, observacion_id=None) -> bool:
    """Ya se mandó la alerta de esta banda para este trámite/observación (sin importar el día exacto)."""
    query = (
        db.query(models.Alerta)
        .filter(models.Alerta.tramite_id == tramite_id)
        .filter(models.Alerta.dias_previos == banda)
        .filter(models.Alerta.enviada.is_(True))
    )
    if observacion_id:
        query = query.filter(models.Alerta.observacion_id == observacion_id)
    else:
        query = query.filter(models.Alerta.observacion_id.is_(None))
    return query.first() is not None


def registrar_envio(db: Session, tramite_id, banda: int, fecha_vencimiento: date, ok: bool, observacion_id=None):
    alerta = models.Alerta(
        tramite_id=tramite_id,
        observacion_id=observacion_id,
        dias_previos=banda,
        fecha_programada=fecha_vencimiento,
        enviada=ok,
        enviada_en=datetime.utcnow() if ok else None,
        canal="email",
    )
    db.add(alerta)
    db.commit()


def construir_html(empresa_nombre, tramite_nombre, categoria, numero_expediente, fecha_vencimiento, dias_restantes, banda):
    return f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
      <h2 style="color:#182821;">Vencimiento próximo (banda de {banda} días)</h2>
      <p><strong>Empresa:</strong> {empresa_nombre}</p>
      <p><strong>Trámite:</strong> {tramite_nombre} ({categoria})</p>
      <p><strong>N° expediente:</strong> {numero_expediente or "—"}</p>
      <p><strong>Fecha de vencimiento:</strong> {fecha_vencimiento} (faltan {dias_restantes} días)</p>
      <p style="color:#4b5a50; font-size: 13px; margin-top: 24px;">
        Enviado automáticamente por {config.APP_NAME}.
      </p>
    </div>
    """


def construir_html_observacion(empresa_nombre, tramite_nombre, categoria, numero_expediente, numero_observacion, motivo, fecha_vencimiento, dias_restantes, banda):
    return f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
      <h2 style="color:#a23328;">Observación N° {numero_observacion} — banda de {banda} días</h2>
      <p><strong>Empresa:</strong> {empresa_nombre}</p>
      <p><strong>Trámite:</strong> {tramite_nombre} ({categoria})</p>
      <p><strong>N° expediente:</strong> {numero_expediente or "—"}</p>
      <p><strong>Motivo:</strong> {motivo or "—"}</p>
      <p><strong>Fecha límite para responder:</strong> {fecha_vencimiento} (faltan {dias_restantes} días)</p>
      <p style="color:#4b5a50; font-size: 13px; margin-top: 24px;">
        Enviado automáticamente por {config.APP_NAME}.
      </p>
    </div>
    """


def ejecutar_revision_alertas() -> dict:
    db = SessionLocal()
    enviadas = 0
    revisadas = 0
    hoy = date.today()
    techo_tramite = max(UMBRALES_TRAMITE)
    techo_observacion = max(UMBRALES_OBSERVACION)

    try:
        # --- Vencimientos normales del trámite (licencias, registros) ---
        tramites = (
            db.query(models.Tramite)
            .options(joinedload(models.Tramite.empresa_cliente), joinedload(models.Tramite.tipo_tramite))
            .filter(models.Tramite.fecha_vencimiento.isnot(None))
            .filter(models.Tramite.fecha_vencimiento >= hoy)
            .all()
        )
        for t in tramites:
            dias_restantes = (t.fecha_vencimiento - hoy).days
            if dias_restantes > techo_tramite:
                continue
            banda = banda_para(dias_restantes, UMBRALES_TRAMITE)
            if banda is None:
                continue

            revisadas += 1
            if ya_fue_enviada(db, t.id, banda):
                continue

            destinatarios = destinatarios_para_empresa(db, t.empresa_cliente_id)
            html = construir_html(
                t.empresa_cliente.nombre,
                t.tipo_tramite.nombre,
                t.tipo_tramite.categoria,
                t.numero_expediente,
                t.fecha_vencimiento,
                dias_restantes,
                banda,
            )
            ok = enviar_correo(
                destinatarios,
                f"Vence pronto ({dias_restantes} días): {t.tipo_tramite.nombre} — {t.empresa_cliente.nombre}",
                html,
            )
            registrar_envio(db, t.id, banda, t.fecha_vencimiento, ok)
            if ok:
                enviadas += 1

        # --- Plazos de respuesta a observaciones de la entidad ---
        observaciones = (
            db.query(models.Observacion)
            .options(
                joinedload(models.Observacion.tramite).joinedload(models.Tramite.empresa_cliente),
                joinedload(models.Observacion.tramite).joinedload(models.Tramite.tipo_tramite),
            )
            .filter(models.Observacion.fecha_vencimiento.isnot(None))
            .filter(models.Observacion.fecha_vencimiento >= hoy)
            .filter(models.Observacion.fecha_respuesta.is_(None))  # ya respondida = nada que avisar
            .all()
        )
        for o in observaciones:
            dias_restantes = (o.fecha_vencimiento - hoy).days
            if dias_restantes > techo_observacion:
                continue
            banda = banda_para(dias_restantes, UMBRALES_OBSERVACION)
            if banda is None:
                continue

            revisadas += 1
            if ya_fue_enviada(db, o.tramite_id, banda, observacion_id=o.id):
                continue

            t = o.tramite
            destinatarios = destinatarios_para_empresa(db, t.empresa_cliente_id)
            html = construir_html_observacion(
                t.empresa_cliente.nombre,
                t.tipo_tramite.nombre,
                t.tipo_tramite.categoria,
                t.numero_expediente,
                o.numero,
                o.motivo,
                o.fecha_vencimiento,
                dias_restantes,
                banda,
            )
            ok = enviar_correo(
                destinatarios,
                f"Observación N° {o.numero} vence pronto ({dias_restantes} días): {t.tipo_tramite.nombre} — {t.empresa_cliente.nombre}",
                html,
            )
            registrar_envio(db, t.id, banda, o.fecha_vencimiento, ok, observacion_id=o.id)
            if ok:
                enviadas += 1
    finally:
        db.close()

    return {"revisadas": revisadas, "enviadas": enviadas}


if __name__ == "__main__":
    resultado = ejecutar_revision_alertas()
    print("Revisión de alertas completada:", resultado)
