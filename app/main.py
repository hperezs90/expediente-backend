import csv
import io
from datetime import date, timedelta
from typing import List
from uuid import UUID

from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import asc, func
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from . import config, models, schemas, auth, storage, tenants
from .tenancy import TenantInfo, get_db, obtener_tenant, obtener_tenant_opcional
from .limites import limiter, obtener_ip_real
from .plataforma import router as plataforma_router
from .alertas_job import ejecutar_revision_alertas

# Las tablas de cada empresa se crean al provisionarla (python -m app.tenants crear); aquí solo el registro de empresas.
tenants.asegurar_tablas_control()
tenants.asegurar_admin_inicial()

app = FastAPI(title="Expediente API")

# CORS abierto: la seguridad real la da el token JWT en cada petición, no el origen.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.include_router(plataforma_router)


def empresas_asignadas_ids(db: Session, usuario_id) -> list:
    filas = (
        db.query(models.UsuarioEmpresaCliente.empresa_cliente_id)
        .filter(models.UsuarioEmpresaCliente.usuario_id == usuario_id)
        .all()
    )
    return [f[0] for f in filas]


def verificar_acceso_empresa(db: Session, current_user: models.Usuario, empresa_id) -> None:
    """Lanza 403 si un gestor intenta acceder a una empresa que no tiene asignada."""
    if current_user.rol == "admin":
        return
    asignadas = empresas_asignadas_ids(db, current_user.id)
    if empresa_id not in asignadas:
        raise HTTPException(status_code=403, detail="No tienes esta empresa asignada")


def _url_descarga_segura(clave: str) -> str | None:
    try:
        return storage.generar_url_descarga(clave)
    except Exception:
        return None


def ultima_observacion(t: models.Tramite) -> models.Observacion | None:
    return max(t.observaciones, key=lambda o: o.numero) if t.observaciones else None


def fecha_limite_observacion_pendiente(t: models.Tramite) -> date | None:
    """Si hay una observación esperando respuesta, devuelve su fecha límite (para la cuenta regresiva)."""
    ultima = ultima_observacion(t)
    if ultima and not ultima.fecha_respuesta:
        return ultima.fecha_vencimiento
    return None


def calcular_estatus(t: models.Tramite) -> str | None:
    """Estatus derivado del flujo: resolución final > observación abierta > última etapa con fecha."""
    if t.resolucion_final == "rechazado":
        return "RECHAZADO"
    if t.resolucion_final == "aprobado":
        return "APROBADO"
    if t.resolucion_final == "finalizado":
        return "FINALIZADO"

    ultima = ultima_observacion(t)
    if ultima:
        if not ultima.fecha_respuesta:
            return f"OBSERVACIÓN N° {ultima.numero} PENDIENTE"
        return "RESPUESTA EN REVISIÓN"

    etapas = t.tipo_tramite.etapas or []
    fechas = t.etapas_fechas or {}
    for etapa in reversed(etapas):
        if fechas.get(etapa):
            return etapa.upper()
    return "EN PREPARACIÓN" if etapas else None  # sin etapas definidas: se usa el campo "estado" manual


def fecha_vencimiento_desde(tipo: models.TipoTramite, base: date) -> date | None:
    if not tipo.vigencia_meses or not base:
        return None
    return base + relativedelta(months=tipo.vigencia_meses)


def crear_renovacion(db: Session, original: models.Tramite, usuario: models.Usuario, fecha_inicio: date | None = None) -> models.Tramite:
    """Crea el trámite que renueva (o continúa) a `original`: misma empresa, tipo, gestor y datos de identificación,
    con checklist nuevo y sin documentos, observaciones ni número de expediente (es una gestión nueva)."""
    tipo = original.tipo_tramite
    inicio = fecha_inicio or date.today()
    nuevo = models.Tramite(
        empresa_cliente_id=original.empresa_cliente_id,
        tipo_tramite_id=tipo.id,
        asignado_a=original.asignado_a,
        creado_por_id=usuario.id,
        fecha_inicio=inicio,
        descripcion=original.descripcion,
        numero_registro=original.numero_registro,
        renueva_a_id=original.id,
        checklist=[{"item": doc, "completado": False} for doc in (tipo.checklist_default or [])],
    )
    if tipo.vigencia_desde == "inicio":
        nuevo.fecha_vencimiento = fecha_vencimiento_desde(tipo, inicio)
    db.add(nuevo)
    db.flush()

    for tramite_id, texto in ((nuevo.id, f"Renovación de un trámite anterior (inicio {inicio})"), (original.id, "Renovación iniciada")):
        db.add(models.AuditoriaTramite(
            tramite_id=tramite_id,
            empresa_id=original.empresa_cliente_id,
            empresa_nombre=original.empresa_cliente.nombre,
            tramite_nombre=tipo.nombre,
            usuario_id=usuario.id,
            campo="renovacion",
            valor_anterior=None,
            valor_nuevo=texto,
        ))
    return nuevo


def construir_tramite_out(t: models.Tramite) -> schemas.TramiteEmpresaOut:
    return schemas.TramiteEmpresaOut(
        id=t.id,
        tramite_nombre=t.tipo_tramite.nombre,
        categoria=t.tipo_tramite.categoria,
        vigencia_meses=t.tipo_tramite.vigencia_meses,
        vigencia_desde=t.tipo_tramite.vigencia_desde or "aprobacion",
        etapas=t.tipo_tramite.etapas or [],
        numero_expediente=t.numero_expediente,
        fecha_inicio=t.fecha_inicio,
        fecha_vencimiento=t.fecha_vencimiento,
        estado=t.estado,
        checklist=t.checklist or [],
        creado_por_nombre=t.creado_por.nombre if t.creado_por else None,
        asignado_a=t.asignado_a,
        asignado_a_nombre=t.asignado_a_usuario.nombre if t.asignado_a_usuario else None,
        resolucion_final=t.resolucion_final,
        fecha_aprobacion=t.fecha_aprobacion,
        etapas_fechas=t.etapas_fechas or {},
        renueva_a_id=t.renueva_a_id,
        renovado_por_id=t.renovaciones[0].id if t.renovaciones else None,
        anticipo=t.anticipo,
        complemento=t.complemento,
        descripcion=t.descripcion,
        numero_registro=t.numero_registro,
        documentos=[
            schemas.DocumentoOut(
                id=d.id,
                tipo=d.tipo,
                nombre_archivo=d.nombre_archivo,
                tamano_bytes=d.tamano_bytes,
                version=d.version or 1,
                subido_por_nombre=d.subido_por.nombre if d.subido_por else None,
                creado_en=d.creado_en,
                url_descarga=_url_descarga_segura(d.clave_almacenamiento),
                observacion_id=d.observacion_id,
            )
            for d in t.documentos
        ],
        observaciones=[schemas.ObservacionOut.model_validate(o) for o in sorted(t.observaciones, key=lambda o: o.numero)],
        estatus_calculado=calcular_estatus(t),
    )


def construir_dashboard_out(t: models.Tramite) -> schemas.TramiteDashboardOut:
    return schemas.TramiteDashboardOut(
        id=t.id,
        empresa_id=t.empresa_cliente_id,
        empresa_nombre=t.empresa_cliente.nombre,
        tramite_nombre=t.tipo_tramite.nombre,
        categoria=t.tipo_tramite.categoria,
        numero_expediente=t.numero_expediente,
        descripcion=t.descripcion,
        renovado=bool(t.renovaciones),
        fecha_vencimiento=t.fecha_vencimiento,
        estado=t.estado,
        creado_por_nombre=t.creado_por.nombre if t.creado_por else None,
        asignado_a_nombre=t.asignado_a_usuario.nombre if t.asignado_a_usuario else None,
        estatus_calculado=calcular_estatus(t),
        creado_en=t.creado_en,
        fecha_limite_observacion=fecha_limite_observacion_pendiente(t),
    )


TRAMITE_JOINS = (
    joinedload(models.Tramite.tipo_tramite),
    joinedload(models.Tramite.creado_por),
    joinedload(models.Tramite.asignado_a_usuario),
    joinedload(models.Tramite.empresa_cliente),
    joinedload(models.Tramite.observaciones),
    selectinload(models.Tramite.renovaciones),
    joinedload(models.Tramite.documentos).joinedload(models.Documento.subido_por),
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/config", response_model=schemas.ConfigPublica)
def configuracion_publica(tenant: TenantInfo | None = Depends(obtener_tenant_opcional)):
    """Identidad visual y parámetros que el frontend necesita antes de iniciar sesión.
    Cada empresa puede tener su propia marca; lo que no defina usa los valores de la instalación."""
    return schemas.ConfigPublica(
        app_name=(tenant and tenant.nombre_app) or config.APP_NAME,
        tagline=(tenant and tenant.eslogan) or config.APP_TAGLINE,
        primary_color=(tenant and tenant.color_primario) or config.APP_PRIMARY_COLOR,
        logo_url=(tenant and tenant.logo_url) or config.APP_LOGO_URL,
        inactividad_minutos=config.INACTIVIDAD_MINUTOS,
        plazo_observacion_meses=config.PLAZO_OBSERVACION_MESES,
        ventana_renovacion_dias=config.VENTANA_RENOVACION_DIAS,
        dominio_base=config.BASE_DOMAIN,
    )


@app.post("/admin/enviar-alertas")
def enviar_alertas_manual(
    current_user: models.Usuario = Depends(auth.require_admin),
    tenant: TenantInfo = Depends(obtener_tenant),
):
    return ejecutar_revision_alertas(tenant)


# ---------- Autenticación ----------
@app.post("/auth/login", response_model=schemas.Token)
@limiter.limit("10/minute")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    tenant: TenantInfo = Depends(obtener_tenant),
):
    user = auth.authenticate_user(db, form_data.username, form_data.password)

    db.add(
        models.IntentoLogin(
            email_intentado=form_data.username,
            ip=obtener_ip_real(request),
            exitoso=user is not None,
        )
    )
    db.commit()

    if not user:
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")
    token = auth.create_access_token(data={"sub": str(user.id), "tenant": tenant.subdominio})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/auth/me", response_model=schemas.UsuarioOut)
def me(current_user: models.Usuario = Depends(auth.get_current_user)):
    return current_user


@app.get("/intentos-login", response_model=List[schemas.IntentoLoginOut])
def listar_intentos_login(
    solo_fallidos: bool = False,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    query = db.query(models.IntentoLogin)
    if solo_fallidos:
        query = query.filter(models.IntentoLogin.exitoso.is_(False))
    return query.order_by(models.IntentoLogin.creado_en.desc()).limit(limit).all()


# ---------- Empresas cliente ----------
@app.get("/empresas", response_model=List[schemas.EmpresaClienteOut])
def listar_empresas(
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    query = db.query(models.EmpresaCliente)
    if current_user.rol != "admin":
        asignadas = empresas_asignadas_ids(db, current_user.id)
        query = query.filter(models.EmpresaCliente.id.in_(asignadas))
    if q:
        query = query.filter(models.EmpresaCliente.nombre.ilike(f"%{q}%"))
    return query.order_by(models.EmpresaCliente.nombre).offset(offset).limit(min(limit, 200)).all()


@app.post("/empresas", response_model=schemas.EmpresaClienteOut)
def crear_empresa(
    empresa: schemas.EmpresaClienteCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    org = db.query(models.Organizacion).first()
    if not org:
        raise HTTPException(status_code=500, detail="No hay ninguna organización creada todavía")

    nueva = models.EmpresaCliente(organizacion_id=org.id, **empresa.model_dump())
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return nueva


@app.get("/empresas/{empresa_id}", response_model=schemas.EmpresaClienteOut)
def obtener_empresa(
    empresa_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    verificar_acceso_empresa(db, current_user, empresa_id)
    empresa = db.query(models.EmpresaCliente).filter(models.EmpresaCliente.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return empresa


@app.patch("/empresas/{empresa_id}", response_model=schemas.EmpresaClienteOut)
def editar_empresa(
    empresa_id: UUID,
    cambios: schemas.EmpresaClienteUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    empresa = db.query(models.EmpresaCliente).filter(models.EmpresaCliente.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    for campo, valor in cambios.model_dump(exclude_unset=True).items():
        setattr(empresa, campo, valor)

    db.commit()
    db.refresh(empresa)
    return empresa


# ---------- Usuarios (gestión de cuentas, solo admin) ----------
@app.get("/gestores", response_model=List[schemas.UsuarioOut])
def listar_gestores_disponibles(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    return (
        db.query(models.Usuario)
        .filter(models.Usuario.activo.is_(True))
        .order_by(models.Usuario.nombre)
        .all()
    )


@app.get("/usuarios", response_model=List[schemas.UsuarioOut])
def listar_usuarios(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    return db.query(models.Usuario).order_by(models.Usuario.nombre).all()


@app.post("/usuarios", response_model=schemas.UsuarioOut)
def crear_usuario(
    datos: schemas.UsuarioCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    existente = db.query(models.Usuario).filter(models.Usuario.email == datos.email).first()
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe un usuario con ese correo")

    org = db.query(models.Organizacion).first()
    nuevo = models.Usuario(
        organizacion_id=org.id,
        nombre=datos.nombre,
        email=datos.email,
        password_hash=auth.hash_password(datos.password),
        rol=datos.rol,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


@app.patch("/usuarios/{usuario_id}", response_model=schemas.UsuarioOut)
def editar_usuario(
    usuario_id: UUID,
    cambios: schemas.UsuarioUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if usuario.id == current_user.id and cambios.rol and cambios.rol != "admin":
        raise HTTPException(status_code=400, detail="No puedes quitarte a ti mismo el rol de admin")

    for campo, valor in cambios.model_dump(exclude_unset=True).items():
        setattr(usuario, campo, valor)

    db.commit()
    db.refresh(usuario)
    return usuario


@app.patch("/usuarios/{usuario_id}/password", response_model=schemas.UsuarioOut)
def cambiar_password_usuario(
    usuario_id: UUID,
    datos: schemas.UsuarioPasswordUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    """Un admin puede resetear la contraseña de cualquier usuario (incluida la suya)."""
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    usuario.password_hash = auth.hash_password(datos.password)
    db.commit()
    db.refresh(usuario)
    return usuario


@app.get("/empresas/{empresa_id}/gestores", response_model=List[schemas.UsuarioOut])
def listar_gestores_de_empresa(
    empresa_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    return (
        db.query(models.Usuario)
        .join(models.UsuarioEmpresaCliente, models.UsuarioEmpresaCliente.usuario_id == models.Usuario.id)
        .filter(models.UsuarioEmpresaCliente.empresa_cliente_id == empresa_id)
        .all()
    )


@app.put("/empresas/{empresa_id}/gestores")
def asignar_gestores(
    empresa_id: UUID,
    datos: schemas.AsignacionEmpresas,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    db.query(models.UsuarioEmpresaCliente).filter(
        models.UsuarioEmpresaCliente.empresa_cliente_id == empresa_id
    ).delete()
    for usuario_id in datos.usuario_ids:
        db.add(models.UsuarioEmpresaCliente(usuario_id=usuario_id, empresa_cliente_id=empresa_id))
    db.commit()
    return {"status": "ok"}


# ---------- Tipos de trámite (catálogo) ----------
def construir_tipo_tramite_out(t: models.TipoTramite, conteo: int = 0) -> schemas.TipoTramiteOut:
    return schemas.TipoTramiteOut(
        id=t.id,
        categoria=t.categoria,
        nombre=t.nombre,
        institucion=t.institucion,
        tipo_gestion=t.tipo_gestion,
        vigencia_meses=t.vigencia_meses,
        vigencia_desde=t.vigencia_desde or "aprobacion",
        etapas=t.etapas or [],
        es_recurrente=t.es_recurrente,
        frecuencia_dias=t.frecuencia_dias,
        checklist_default=t.checklist_default or [],
        notas=t.notas,
        activo=t.activo,
        tramites_asociados=conteo,
    )


@app.get("/tipos-tramite", response_model=List[schemas.TipoTramiteOut])
def listar_tipos_tramite(
    categoria: str = "",
    incluir_inactivos: bool = False,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    query = db.query(models.TipoTramite)
    if categoria:
        query = query.filter(models.TipoTramite.categoria == categoria.lower())
    if not incluir_inactivos:
        # El picker de "Nuevo trámite" no debe ofrecer tipos retirados del catálogo.
        # El panel de mantenimiento del catálogo sí manda incluir_inactivos=true.
        query = query.filter(models.TipoTramite.activo.is_(True))
    tipos = query.order_by(models.TipoTramite.categoria, models.TipoTramite.nombre).all()

    conteos = dict(
        db.query(models.Tramite.tipo_tramite_id, func.count(models.Tramite.id))
        .group_by(models.Tramite.tipo_tramite_id)
        .all()
    )
    return [construir_tipo_tramite_out(t, conteos.get(t.id, 0)) for t in tipos]


@app.post("/tipos-tramite", response_model=schemas.TipoTramiteOut)
def crear_tipo_tramite(
    datos: schemas.TipoTramiteCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    datos_tipo = datos.model_dump()
    datos_tipo["categoria"] = datos_tipo["categoria"].strip().lower()
    datos_tipo["etapas"] = [e.strip() for e in datos_tipo["etapas"] if e.strip()]
    nuevo = models.TipoTramite(**datos_tipo)
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return construir_tipo_tramite_out(nuevo, 0)


@app.patch("/tipos-tramite/{tipo_id}", response_model=schemas.TipoTramiteOut)
def editar_tipo_tramite(
    tipo_id: UUID,
    cambios: schemas.TipoTramiteUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    tipo = db.query(models.TipoTramite).filter(models.TipoTramite.id == tipo_id).first()
    if not tipo:
        raise HTTPException(status_code=404, detail="Tipo de trámite no encontrado")

    for campo, valor in cambios.model_dump(exclude_unset=True).items():
        if campo == "categoria" and valor:
            valor = valor.strip().lower()
        if campo == "etapas" and valor is not None:
            valor = [e.strip() for e in valor if e.strip()]
        setattr(tipo, campo, valor)

    db.commit()
    db.refresh(tipo)
    conteo = db.query(models.Tramite).filter(models.Tramite.tipo_tramite_id == tipo.id).count()
    return construir_tipo_tramite_out(tipo, conteo)


@app.delete("/tipos-tramite/{tipo_id}")
def borrar_tipo_tramite(
    tipo_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    tipo = db.query(models.TipoTramite).filter(models.TipoTramite.id == tipo_id).first()
    if not tipo:
        raise HTTPException(status_code=404, detail="Tipo de trámite no encontrado")

    en_uso = db.query(models.Tramite).filter(models.Tramite.tipo_tramite_id == tipo_id).count()
    if en_uso > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No se puede borrar: {en_uso} trámite(s) usan este tipo. "
                "Márcalo como inactivo en vez de borrarlo — así deja de ofrecerse para trámites "
                "nuevos, pero los que ya existen no se rompen."
            ),
        )

    db.delete(tipo)
    db.commit()
    return {"status": "ok"}


# ---------- Trámites ----------
@app.post("/tramites/importar-csv", response_model=schemas.ImportacionResultado)
def importar_tramites_csv(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    """
    Columnas esperadas en el CSV (con encabezados exactos):
    empresa_nombre, categoria, tipo_tramite_nombre, tipo_gestion (opcional),
    fecha_inicio, numero_expediente (opcional), fecha_vencimiento (opcional)
    """
    org = db.query(models.Organizacion).first()

    contenido = archivo.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(contenido))

    errores = []
    creados = 0
    empresas_creadas = 0
    empresas_cache = {}
    total_filas = 0

    for i, fila in enumerate(reader, start=2):  # fila 1 es el encabezado
        total_filas += 1
        try:
            empresa_nombre = (fila.get("empresa_nombre") or "").strip()
            categoria = (fila.get("categoria") or "").strip().lower()
            tipo_nombre = (fila.get("tipo_tramite_nombre") or "").strip()
            tipo_gestion = (fila.get("tipo_gestion") or "").strip()
            fecha_inicio_raw = (fila.get("fecha_inicio") or "").strip()
            numero_expediente = (fila.get("numero_expediente") or "").strip() or None
            fecha_vencimiento_raw = (fila.get("fecha_vencimiento") or "").strip()

            if not empresa_nombre or not categoria or not tipo_nombre or not fecha_inicio_raw:
                errores.append(schemas.ImportacionError(
                    fila=i, motivo="Faltan datos obligatorios (empresa, categoría, tipo de trámite o fecha de inicio)"
                ))
                continue

            fecha_inicio = date_parser.parse(fecha_inicio_raw, dayfirst=True).date()
            fecha_vencimiento = None
            if fecha_vencimiento_raw:
                fecha_vencimiento = date_parser.parse(fecha_vencimiento_raw, dayfirst=True).date()

            # Buscar o crear la empresa
            clave_empresa = empresa_nombre.lower()
            if clave_empresa in empresas_cache:
                empresa = empresas_cache[clave_empresa]
            else:
                empresa = (
                    db.query(models.EmpresaCliente)
                    .filter(models.EmpresaCliente.nombre.ilike(empresa_nombre))
                    .first()
                )
                if not empresa:
                    empresa = models.EmpresaCliente(organizacion_id=org.id, nombre=empresa_nombre)
                    db.add(empresa)
                    db.flush()
                    empresas_creadas += 1
                empresas_cache[clave_empresa] = empresa

            # Buscar el tipo de trámite en el catálogo
            tipo_query = db.query(models.TipoTramite).filter(
                models.TipoTramite.categoria == categoria,
                models.TipoTramite.nombre.ilike(tipo_nombre),
            )
            if tipo_gestion:
                tipo_query = tipo_query.filter(models.TipoTramite.tipo_gestion.ilike(tipo_gestion))
            tipo = tipo_query.first()

            if not tipo:
                errores.append(schemas.ImportacionError(
                    fila=i,
                    motivo=f"No se encontró en el catálogo: categoría '{categoria}', trámite '{tipo_nombre}'"
                    + (f", gestión '{tipo_gestion}'" if tipo_gestion else ""),
                ))
                continue

            # Mismo criterio que crear_tramite: solo si el tipo cuenta la vigencia desde el inicio.
            if not fecha_vencimiento and tipo.vigencia_desde == "inicio":
                fecha_vencimiento = fecha_vencimiento_desde(tipo, fecha_inicio)

            nuevo = models.Tramite(
                empresa_cliente_id=empresa.id,
                tipo_tramite_id=tipo.id,
                numero_expediente=numero_expediente,
                fecha_inicio=fecha_inicio,
                fecha_vencimiento=fecha_vencimiento,
                creado_por_id=current_user.id,
                checklist=[{"item": doc, "completado": False} for doc in (tipo.checklist_default or [])],
            )
            db.add(nuevo)
            creados += 1

        except Exception as e:
            errores.append(schemas.ImportacionError(fila=i, motivo=f"Error inesperado: {str(e)}"))

    db.commit()

    return schemas.ImportacionResultado(
        total_filas=total_filas,
        creados=creados,
        empresas_creadas=empresas_creadas,
        errores=errores,
    )


@app.get("/tramites/buscar", response_model=List[schemas.TramiteDashboardOut])
def buscar_tramites(
    q: str = "",
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    if not q or len(q) < 2:
        return []

    query = (
        db.query(models.Tramite)
        .options(
            joinedload(models.Tramite.empresa_cliente),
            joinedload(models.Tramite.tipo_tramite),
            joinedload(models.Tramite.creado_por),
            joinedload(models.Tramite.asignado_a_usuario),
            joinedload(models.Tramite.observaciones),
            selectinload(models.Tramite.renovaciones),
        )
        .filter(models.Tramite.numero_expediente.ilike(f"%{q}%"))
    )
    if current_user.rol != "admin":
        asignadas = empresas_asignadas_ids(db, current_user.id)
        query = query.filter(models.Tramite.empresa_cliente_id.in_(asignadas))

    tramites = query.limit(20).all()
    return [construir_dashboard_out(t) for t in tramites]


@app.get("/dashboard/resumen", response_model=schemas.DashboardResumen)
def resumen_dashboard(
    gestor_id: str = "",
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    query = db.query(models.EmpresaCliente)
    if current_user.rol != "admin":
        asignadas = empresas_asignadas_ids(db, current_user.id)
        query = query.filter(models.EmpresaCliente.id.in_(asignadas))
    elif gestor_id:
        asignadas = empresas_asignadas_ids(db, gestor_id)
        query = query.filter(models.EmpresaCliente.id.in_(asignadas))

    empresas = query.all()
    total = len(empresas)
    sin_tramites = sum(1 for e in empresas if len(e.tramites) == 0)
    return schemas.DashboardResumen(total_empresas=total, empresas_sin_tramites=sin_tramites)


@app.get("/dashboard/proximos-vencer", response_model=List[schemas.TramiteDashboardOut])
def proximos_a_vencer(
    gestor_id: str = "",
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    # Trae TODOS los trámites (con o sin vencimiento todavía) — el filtro de días
    # ahora se aplica del lado del frontend, sobre esta misma lista completa.
    query = db.query(models.Tramite).options(
        joinedload(models.Tramite.empresa_cliente),
        joinedload(models.Tramite.tipo_tramite),
        joinedload(models.Tramite.creado_por),
        joinedload(models.Tramite.asignado_a_usuario),
        joinedload(models.Tramite.observaciones),
        selectinload(models.Tramite.renovaciones),
    )
    if current_user.rol != "admin":
        asignadas = empresas_asignadas_ids(db, current_user.id)
        query = query.filter(models.Tramite.empresa_cliente_id.in_(asignadas))
    elif gestor_id:
        asignadas = empresas_asignadas_ids(db, gestor_id)
        query = query.filter(models.Tramite.empresa_cliente_id.in_(asignadas))

    # Los que sí tienen vencimiento van primero (más próximo primero); los que
    # todavía no tienen (con observación abierta, pendientes de aprobación) van al final,
    # ordenados por los más recientes primero.
    tramites = query.order_by(
        models.Tramite.fecha_vencimiento.is_(None),
        asc(models.Tramite.fecha_vencimiento),
        models.Tramite.creado_en.desc(),
    ).all()

    return [construir_dashboard_out(t) for t in tramites]


@app.post("/tramites", response_model=schemas.TramiteOut)
def crear_tramite(
    tramite: schemas.TramiteCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    verificar_acceso_empresa(db, current_user, tramite.empresa_cliente_id)

    tipo = db.query(models.TipoTramite).filter(models.TipoTramite.id == tramite.tipo_tramite_id).first()
    if not tipo:
        raise HTTPException(status_code=404, detail="Tipo de trámite no encontrado")

    # Autocompleta fecha de vencimiento y checklist según el catálogo.
    # Si la vigencia cuenta desde la aprobación, el vencimiento se calcula después, en editar_tramite.
    data = tramite.model_dump()
    if tipo.vigencia_desde == "inicio" and not data.get("fecha_vencimiento"):
        data["fecha_vencimiento"] = fecha_vencimiento_desde(tipo, data["fecha_inicio"])

    nuevo = models.Tramite(**data)
    nuevo.creado_por_id = current_user.id
    nuevo.checklist = [{"item": doc, "completado": False} for doc in (tipo.checklist_default or [])]
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


@app.get("/empresas/{empresa_id}/tramites", response_model=List[schemas.TramiteEmpresaOut])
def tramites_de_empresa(
    empresa_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    verificar_acceso_empresa(db, current_user, empresa_id)
    tramites = (
        db.query(models.Tramite)
        .options(*TRAMITE_JOINS)
        .filter(models.Tramite.empresa_cliente_id == empresa_id)
        .order_by(models.Tramite.fecha_vencimiento)
        .all()
    )
    return [construir_tramite_out(t) for t in tramites]


@app.patch("/tramites/{tramite_id}", response_model=schemas.TramiteEmpresaOut)
def editar_tramite(
    tramite_id: UUID,
    cambios: schemas.TramiteUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    tramite = (
        db.query(models.Tramite)
        .options(*TRAMITE_JOINS)
        .filter(models.Tramite.id == tramite_id)
        .first()
    )
    if not tramite:
        raise HTTPException(status_code=404, detail="Trámite no encontrado")

    CAMPOS_AUDITABLES = {
        "numero_expediente", "fecha_inicio", "fecha_vencimiento", "estado", "asignado_a", "notas",
        "resolucion_final", "fecha_aprobacion", "anticipo", "complemento", "descripcion", "numero_registro",
    }
    cambios_dict = cambios.model_dump(exclude_unset=True)

    # Si la vigencia cuenta desde la aprobación, el vencimiento se recalcula al aprobar
    if (
        tramite.tipo_tramite.vigencia_desde != "inicio"
        and ("fecha_aprobacion" in cambios_dict or cambios_dict.get("resolucion_final") == "aprobado")
        and not cambios_dict.get("fecha_vencimiento")
    ):
        nueva_aprobacion = cambios_dict.get("fecha_aprobacion", tramite.fecha_aprobacion)
        calculado = fecha_vencimiento_desde(tramite.tipo_tramite, nueva_aprobacion)
        if calculado:
            cambios_dict["fecha_vencimiento"] = calculado

    def registrar_cambio(campo, anterior, nuevo):
        db.add(models.AuditoriaTramite(
            tramite_id=tramite.id,
            empresa_id=tramite.empresa_cliente_id,
            empresa_nombre=tramite.empresa_cliente.nombre,
            tramite_nombre=tramite.tipo_tramite.nombre,
            usuario_id=current_user.id,
            campo=campo[:50],
            valor_anterior=str(anterior) if anterior is not None else None,
            valor_nuevo=str(nuevo) if nuevo is not None else None,
        ))

    # Etapas: se audita cada etapa que cambió, con el prefijo "etapa:" para poder mostrarla
    if "etapas_fechas" in cambios_dict:
        nuevas = {k: v for k, v in (cambios_dict.pop("etapas_fechas") or {}).items() if v}
        anteriores = tramite.etapas_fechas or {}
        for etapa in set(nuevas) | set(anteriores):
            antes, despues = anteriores.get(etapa), nuevas.get(etapa)
            if str(antes) != str(despues if despues is None else despues.isoformat()):
                registrar_cambio(f"etapa:{etapa}", antes, despues)
        tramite.etapas_fechas = {k: v.isoformat() for k, v in nuevas.items()}

    for campo, valor_nuevo in cambios_dict.items():
        if campo in CAMPOS_AUDITABLES:
            valor_anterior = getattr(tramite, campo)
            if str(valor_anterior) != str(valor_nuevo):
                registrar_cambio(campo, valor_anterior, valor_nuevo)

    for campo, valor in cambios_dict.items():
        setattr(tramite, campo, valor)

    # Trámites recurrentes (informes periódicos, obligaciones anuales): al cerrarse con éxito se crea solo
    # el siguiente periodo, que arranca cuando vence el actual (o tras la frecuencia indicada en el catálogo).
    tipo = tramite.tipo_tramite
    if (
        cambios_dict.get("resolucion_final") in ("aprobado", "finalizado")
        and tipo.es_recurrente
        and not tramite.renovaciones
    ):
        siguiente = tramite.fecha_vencimiento
        if not siguiente and tipo.frecuencia_dias:
            siguiente = tramite.fecha_inicio + timedelta(days=tipo.frecuencia_dias)
        if siguiente:
            crear_renovacion(db, tramite, current_user, fecha_inicio=siguiente)

    db.commit()
    db.refresh(tramite)
    return construir_tramite_out(tramite)


@app.post("/tramites/{tramite_id}/renovar", response_model=schemas.TramiteEmpresaOut)
def renovar_tramite(
    tramite_id: UUID,
    datos: schemas.RenovarTramite,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    """Renovación en un clic: crea el trámite nuevo a partir del actual y marca el actual como 'renovación en curso'."""
    original = _cargar_tramite_con_joins(db, tramite_id)
    if not original:
        raise HTTPException(status_code=404, detail="Trámite no encontrado")
    verificar_acceso_empresa(db, current_user, original.empresa_cliente_id)
    if original.renovaciones:
        raise HTTPException(status_code=400, detail="Este trámite ya tiene una renovación creada")
    if original.resolucion_final == "rechazado":
        raise HTTPException(status_code=400, detail="Un trámite rechazado no se renueva; crea uno nuevo")

    nuevo = crear_renovacion(db, original, current_user, fecha_inicio=datos.fecha_inicio)
    if original.estado != "renovacion_en_curso":
        db.add(models.AuditoriaTramite(
            tramite_id=original.id,
            empresa_id=original.empresa_cliente_id,
            empresa_nombre=original.empresa_cliente.nombre,
            tramite_nombre=original.tipo_tramite.nombre,
            usuario_id=current_user.id,
            campo="estado",
            valor_anterior=original.estado,
            valor_nuevo="renovacion_en_curso",
        ))
        original.estado = "renovacion_en_curso"
    db.commit()
    return construir_tramite_out(_cargar_tramite_con_joins(db, nuevo.id))


@app.get("/empresas/{empresa_id}/auditoria", response_model=List[schemas.AuditoriaOut])
def historial_empresa(
    empresa_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    verificar_acceso_empresa(db, current_user, empresa_id)
    entradas = (
        db.query(models.AuditoriaTramite)
        .options(joinedload(models.AuditoriaTramite.usuario))
        .filter(models.AuditoriaTramite.empresa_id == empresa_id)
        .order_by(models.AuditoriaTramite.creado_en.desc())
        .limit(200)
        .all()
    )
    return [
        schemas.AuditoriaOut(
            campo=e.campo,
            valor_anterior=e.valor_anterior,
            valor_nuevo=e.valor_nuevo,
            usuario_nombre=e.usuario.nombre if e.usuario else None,
            creado_en=e.creado_en,
            tramite_nombre=e.tramite_nombre,
        )
        for e in entradas
    ]


@app.get("/tramites/{tramite_id}/auditoria", response_model=List[schemas.AuditoriaOut])
def historial_tramite(
    tramite_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    tramite = db.query(models.Tramite).filter(models.Tramite.id == tramite_id).first()
    if not tramite:
        raise HTTPException(status_code=404, detail="Trámite no encontrado")
    verificar_acceso_empresa(db, current_user, tramite.empresa_cliente_id)

    entradas = (
        db.query(models.AuditoriaTramite)
        .options(joinedload(models.AuditoriaTramite.usuario))
        .filter(models.AuditoriaTramite.tramite_id == tramite_id)
        .order_by(models.AuditoriaTramite.creado_en.desc())
        .all()
    )
    return [
        schemas.AuditoriaOut(
            campo=e.campo,
            valor_anterior=e.valor_anterior,
            valor_nuevo=e.valor_nuevo,
            usuario_nombre=e.usuario.nombre if e.usuario else None,
            creado_en=e.creado_en,
        )
        for e in entradas
    ]


def _cargar_tramite_con_joins(db: Session, tramite_id) -> models.Tramite | None:
    return (
        db.query(models.Tramite)
        .options(*TRAMITE_JOINS)
        .filter(models.Tramite.id == tramite_id)
        .first()
    )


@app.post("/tramites/{tramite_id}/observaciones", response_model=schemas.TramiteEmpresaOut)
def crear_observacion(
    tramite_id: UUID,
    datos: schemas.ObservacionCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    tramite = _cargar_tramite_con_joins(db, tramite_id)
    if not tramite:
        raise HTTPException(status_code=404, detail="Trámite no encontrado")
    verificar_acceso_empresa(db, current_user, tramite.empresa_cliente_id)

    data = datos.model_dump()
    existentes = {o.numero for o in tramite.observaciones}
    numero = data.pop("numero") or (max(existentes, default=0) + 1)
    if numero in existentes:
        raise HTTPException(status_code=400, detail=f"Ya existe la observación N° {numero} para este trámite")

    if data.get("fecha_emision") and not data.get("fecha_vencimiento"):
        # El plazo se cuenta en meses calendario (relativedelta, no timedelta(days=90)),
        # y su duración es configurable por instalación (PLAZO_OBSERVACION_MESES).
        data["fecha_vencimiento"] = data["fecha_emision"] + relativedelta(months=config.PLAZO_OBSERVACION_MESES)

    db.add(models.Observacion(tramite_id=tramite.id, numero=numero, **data))
    db.add(models.AuditoriaTramite(
        tramite_id=tramite.id,
        empresa_id=tramite.empresa_cliente_id,
        empresa_nombre=tramite.empresa_cliente.nombre,
        tramite_nombre=tramite.tipo_tramite.nombre,
        usuario_id=current_user.id,
        campo=f"observacion_{numero}",
        valor_anterior=None,
        valor_nuevo=f"Observación N° {numero} registrada",
    ))

    db.commit()
    db.refresh(tramite)
    return construir_tramite_out(tramite)


@app.patch("/observaciones/{observacion_id}", response_model=schemas.TramiteEmpresaOut)
def editar_observacion(
    observacion_id: UUID,
    cambios: schemas.ObservacionUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
):
    observacion = db.query(models.Observacion).filter(models.Observacion.id == observacion_id).first()
    if not observacion:
        raise HTTPException(status_code=404, detail="Observación no encontrada")

    tramite = _cargar_tramite_con_joins(db, observacion.tramite_id)
    verificar_acceso_empresa(db, current_user, tramite.empresa_cliente_id)

    cambios_dict = cambios.model_dump(exclude_unset=True)
    if cambios_dict.get("fecha_emision") and not cambios_dict.get("fecha_vencimiento"):
        cambios_dict["fecha_vencimiento"] = cambios_dict["fecha_emision"] + relativedelta(months=config.PLAZO_OBSERVACION_MESES)

    for campo, valor in cambios_dict.items():
        setattr(observacion, campo, valor)

    db.commit()
    db.refresh(tramite)
    return construir_tramite_out(tramite)


@app.delete("/observaciones/{observacion_id}", response_model=schemas.TramiteEmpresaOut)
def borrar_observacion(
    observacion_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    observacion = db.query(models.Observacion).filter(models.Observacion.id == observacion_id).first()
    if not observacion:
        raise HTTPException(status_code=404, detail="Observación no encontrada")

    tramite = _cargar_tramite_con_joins(db, observacion.tramite_id)
    db.delete(observacion)
    db.commit()
    db.refresh(tramite)
    return construir_tramite_out(tramite)


@app.post("/tramites/{tramite_id}/documentos", response_model=schemas.TramiteEmpresaOut)
def subir_documento(
    tramite_id: UUID,
    tipo: str,
    archivo: UploadFile = File(...),
    observacion_id: str = "",
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.get_current_user),
    tenant: TenantInfo = Depends(obtener_tenant),
):
    if tipo not in ("ingreso", "resolucion", "observacion", "otro"):
        raise HTTPException(status_code=400, detail="Tipo de documento inválido")

    tramite = (
        db.query(models.Tramite)
        .options(*TRAMITE_JOINS)
        .filter(models.Tramite.id == tramite_id)
        .first()
    )
    if not tramite:
        raise HTTPException(status_code=404, detail="Trámite no encontrado")
    verificar_acceso_empresa(db, current_user, tramite.empresa_cliente_id)

    contenido = archivo.file.read()
    error = storage.validar_archivo(archivo.filename, len(contenido), contenido)
    if error:
        raise HTTPException(status_code=400, detail=error)

    try:
        clave = storage.subir_archivo(contenido, archivo.filename, archivo.content_type, prefijo=tenant.subdominio)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    obs_id = UUID(observacion_id) if observacion_id else None
    # Cada subida nueva del mismo documento (mismo trámite, tipo y observación) es una versión más;
    # las anteriores se conservan como historial.
    version = 1 + max(
        (d.version or 1 for d in tramite.documentos if d.tipo == tipo and d.observacion_id == obs_id),
        default=0,
    )

    nuevo = models.Documento(
        tramite_id=tramite.id,
        observacion_id=obs_id,
        version=version,
        tipo=tipo,
        nombre_archivo=archivo.filename,
        clave_almacenamiento=clave,
        tamano_bytes=len(contenido),
        subido_por_id=current_user.id,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(tramite)
    return construir_tramite_out(tramite)


@app.get("/archivos/{clave:path}", include_in_schema=False)
def descargar_archivo_local(clave: str, exp: int, sig: str):
    """Sirve un archivo del almacenamiento local, solo con una URL firmada y vigente."""
    if storage.usa_s3() or not storage.firma_valida(clave, exp, sig):
        raise HTTPException(status_code=403, detail="Enlace inválido o vencido")
    try:
        ruta = storage.leer_ruta_local(clave)
    except ValueError:
        ruta = None
    if not ruta:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    ext = "." + ruta.rsplit(".", 1)[-1].lower()
    return FileResponse(ruta, media_type=storage.TIPOS_MIME.get(ext, "application/octet-stream"))


@app.delete("/documentos/{documento_id}", response_model=schemas.TramiteEmpresaOut)
def borrar_documento(
    documento_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    documento = db.query(models.Documento).filter(models.Documento.id == documento_id).first()
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    tramite = (
        db.query(models.Tramite)
        .options(*TRAMITE_JOINS)
        .filter(models.Tramite.id == documento.tramite_id)
        .first()
    )

    try:
        storage.borrar_archivo(documento.clave_almacenamiento)
    except Exception:
        pass  # si falla borrar del almacenamiento, igual quitamos el registro

    db.delete(documento)
    db.commit()
    db.refresh(tramite)
    return construir_tramite_out(tramite)


@app.delete("/tramites/{tramite_id}", status_code=204)
def borrar_tramite(
    tramite_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(auth.require_admin),
):
    tramite = (
        db.query(models.Tramite)
        .options(joinedload(models.Tramite.tipo_tramite), joinedload(models.Tramite.empresa_cliente))
        .filter(models.Tramite.id == tramite_id)
        .first()
    )
    if not tramite:
        raise HTTPException(status_code=404, detail="Trámite no encontrado")

    db.add(models.AuditoriaTramite(
        tramite_id=tramite.id,
        empresa_id=tramite.empresa_cliente_id,
        empresa_nombre=tramite.empresa_cliente.nombre,
        tramite_nombre=tramite.tipo_tramite.nombre,
        usuario_id=current_user.id,
        campo="eliminado",
        valor_anterior="activo",
        valor_nuevo="trámite eliminado",
    ))
    db.delete(tramite)
    db.commit()
    return None
