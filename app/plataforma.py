"""
API de administración de la plataforma: crear y gestionar empresas (subdominios).

Acceso (cualquiera de los dos):
  - Sesión de administrador de plataforma: POST /plataforma/login -> token (lo usa la pantalla /plataforma del frontend).
  - Encabezado X-Plataforma-Token igual a PLATAFORMA_TOKEN (para automatizaciones). Sin esa variable, este modo no existe.
"""
import hmac
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field, TypeAdapter, field_validator
from sqlalchemy import text

from . import auth, config, emailing, models, tenancy, tenants
from .control import AdminPlataforma, Tenant
from .database import SessionLocal, engine, sesion_tenant
from .limites import limiter

router = APIRouter(prefix="/plataforma", tags=["plataforma"])

CATALOGO_EJEMPLO = os.path.join(tenants.DIR_MIGRACIONES, "..", "datos", "catalogo_ejemplo.csv")


def requerir_plataforma(
    request: Request,
    x_plataforma_token: str = Header(default=""),
) -> str:
    """Autoriza por token de plataforma o por sesión de administrador de plataforma. Devuelve quién es."""
    if config.PLATAFORMA_TOKEN and x_plataforma_token and hmac.compare_digest(x_plataforma_token, config.PLATAFORMA_TOKEN):
        return "token"
    cabecera = request.headers.get("authorization", "")
    if cabecera.lower().startswith("bearer "):
        try:
            payload = jwt.decode(cabecera[7:], auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        except JWTError:
            payload = {}
        if payload.get("plataforma") is True:
            db = SessionLocal()
            try:
                admin = db.query(AdminPlataforma).filter(AdminPlataforma.id == payload.get("sub")).first()
                if admin and admin.activo:
                    return admin.email
            finally:
                db.close()
    raise HTTPException(status_code=401, detail="Sesión de plataforma no válida")


_validador_correo = TypeAdapter(EmailStr)


def _validar_lista_correos(valor):
    """Acepta vacío (volver al valor por defecto) o uno o varios correos válidos separados por coma."""
    if not valor:
        return valor
    correos = emailing.lista_correos(valor)
    for c in correos:
        _validador_correo.validate_python(c)
    return ", ".join(correos)


class TokenPlataforma(BaseModel):
    access_token: str
    token_type: str = "bearer"
    nombre: str
    email: str


@router.post("/login", response_model=TokenPlataforma)
@limiter.limit("10/minute")
def login_plataforma(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    db = SessionLocal()
    try:
        admin = db.query(AdminPlataforma).filter(AdminPlataforma.email == form_data.username).first()
        valido = bool(admin and admin.activo and auth.verify_password(form_data.password, admin.password_hash))
        if not valido:
            raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")
        token = auth.create_access_token(data={"sub": str(admin.id), "plataforma": True})
        return TokenPlataforma(access_token=token, nombre=admin.nombre, email=admin.email)
    finally:
        db.close()


class EmpresaCrear(BaseModel):
    subdominio: str
    nombre: str
    admin_nombre: str
    admin_email: EmailStr
    admin_password: str = Field(min_length=8)
    catalogo_ejemplo: bool = False
    color_primario: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    logo_url: Optional[str] = None
    eslogan: Optional[str] = None
    nombre_app: Optional[str] = None
    correo_alertas: Optional[str] = None  # uno o varios correos separados por coma

    _validar_correos = field_validator("correo_alertas")(lambda v: _validar_lista_correos(v))


class EmpresaEditar(BaseModel):
    nombre: Optional[str] = None
    activo: Optional[bool] = None
    nombre_app: Optional[str] = None
    eslogan: Optional[str] = None
    color_primario: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    logo_url: Optional[str] = None
    correo_alertas: Optional[str] = None

    _validar_correos = field_validator("correo_alertas")(lambda v: _validar_lista_correos(v))


class EmpresaOut(BaseModel):
    subdominio: str
    nombre: str
    activo: bool
    nombre_app: Optional[str] = None
    eslogan: Optional[str] = None
    color_primario: Optional[str] = None
    logo_url: Optional[str] = None
    correo_alertas: Optional[str] = None
    usuarios: Optional[int] = None
    tramites: Optional[int] = None


class ResetPassword(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


def _out(t, con_conteos: bool = False) -> EmpresaOut:
    out = EmpresaOut(
        subdominio=t.subdominio, nombre=t.nombre, activo=t.activo, nombre_app=t.nombre_app,
        eslogan=t.eslogan, color_primario=t.color_primario, logo_url=t.logo_url, correo_alertas=t.correo_alertas,
    )
    if con_conteos:
        try:
            with engine.connect() as conn:
                # El esquema sale del registro (creado a partir de un subdominio validado); aun así va entre comillas
                out.usuarios = conn.execute(text(f'SELECT count(*) FROM "{t.esquema}".usuario')).scalar()
                out.tramites = conn.execute(text(f'SELECT count(*) FROM "{t.esquema}".tramite')).scalar()
        except Exception:
            pass
    return out


@router.get("/yo")
def quien_soy(quien: str = Depends(requerir_plataforma)):
    return {"email": quien}


@router.get("/empresas", response_model=List[EmpresaOut], dependencies=[Depends(requerir_plataforma)])
def listar_empresas():
    return [_out(t, con_conteos=True) for t in tenancy.listar_tenants(solo_activos=False)]


@router.post("/empresas", response_model=EmpresaOut, status_code=201, dependencies=[Depends(requerir_plataforma)])
def crear_empresa(datos: EmpresaCrear):
    marca = {k: v for k, v in datos.model_dump(include={
        "color_primario", "logo_url", "eslogan", "nombre_app", "correo_alertas"
    }).items() if v}
    try:
        t = tenants.provisionar(
            datos.subdominio, datos.nombre, datos.admin_nombre, datos.admin_email, datos.admin_password,
            catalogo=CATALOGO_EJEMPLO if datos.catalogo_ejemplo else None, **marca,
        )
    except tenants.ErrorTenant as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _out(t, con_conteos=True)


@router.patch("/empresas/{subdominio}", response_model=EmpresaOut, dependencies=[Depends(requerir_plataforma)])
def editar_empresa(subdominio: str, cambios: EmpresaEditar):
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter(Tenant.subdominio == subdominio.lower()).first()
        if not t:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")
        for campo, valor in cambios.model_dump(exclude_unset=True).items():
            # Un campo de marca enviado vacío significa "volver al valor por defecto de la instalación"
            setattr(t, campo, valor if valor != "" else None)
        db.commit()
        db.refresh(t)
        resultado = _out(t, con_conteos=True)
    finally:
        db.close()
    tenancy.invalidar_cache()
    return resultado


@router.post("/empresas/{subdominio}/restablecer-password", dependencies=[Depends(requerir_plataforma)])
def restablecer_password(subdominio: str, datos: ResetPassword):
    """Cambia la contraseña de un usuario de la empresa (por ejemplo, cuando el administrador la olvidó)."""
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter(Tenant.subdominio == subdominio.lower()).first()
        if not t:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")
        esquema = t.esquema
    finally:
        db.close()
    sesion = sesion_tenant(esquema)
    try:
        usuario = sesion.query(models.Usuario).filter(models.Usuario.email == datos.email).first()
        if not usuario:
            raise HTTPException(status_code=404, detail="No existe ese usuario en la empresa")
        usuario.password_hash = auth.hash_password(datos.password)
        usuario.activo = True
        sesion.commit()
    finally:
        sesion.close()
    return {"status": "ok"}


@router.post("/empresas/{subdominio}/correo-prueba", dependencies=[Depends(requerir_plataforma)])
def enviar_correo_prueba(subdominio: str):
    """Manda un correo de prueba al correo de alertas de la empresa, para comprobar Resend y el remitente."""
    t = tenancy.buscar_tenant(subdominio.lower())
    if not t:
        raise HTTPException(status_code=404, detail="Empresa no encontrada o inactiva")
    destinatarios = emailing.lista_correos(t.correo_alertas) or emailing.lista_correos(os.getenv("CORREO_UNICO_ALERTAS", ""))
    nombre_app = t.nombre_app or config.APP_NAME
    ok, error = emailing.enviar_correo_detallado(
        destinatarios,
        f"Correo de prueba — {nombre_app}",
        f"<p>Este es un correo de prueba de <strong>{nombre_app}</strong> para <strong>{t.nombre}</strong>. "
        "Si lo recibes, las alertas por correo están bien configuradas.</p>",
        nombre_app,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=error)
    return {"enviado_a": destinatarios, "remitente": emailing.remitente(nombre_app)}
