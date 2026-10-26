import re
import time
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request

from . import config
from .control import Tenant
from .database import SessionLocal, sesion_tenant

_PATRON_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,40}[a-z0-9])?$")
_TTL_CACHE_SEGUNDOS = 30
_cache: dict = {}


@dataclass(frozen=True)
class TenantInfo:
    id: UUID
    subdominio: str
    esquema: str
    nombre: str
    activo: bool
    nombre_app: Optional[str]
    eslogan: Optional[str]
    color_primario: Optional[str]
    logo_url: Optional[str]
    correo_alertas: Optional[str]


def slug_valido(slug: str) -> bool:
    return bool(_PATRON_SLUG.match(slug or "")) and slug not in config.SUBDOMINIOS_RESERVADOS


def esquema_de(slug: str) -> str:
    # El nombre del esquema se usa en DDL: solo sale de un slug ya validado (a-z, 0-9, guion)
    return "t_" + slug.replace("-", "_")


def a_info(t: Tenant) -> TenantInfo:
    return TenantInfo(
        id=t.id, subdominio=t.subdominio, esquema=t.esquema, nombre=t.nombre, activo=t.activo,
        nombre_app=t.nombre_app, eslogan=t.eslogan, color_primario=t.color_primario,
        logo_url=t.logo_url, correo_alertas=t.correo_alertas,
    )


def invalidar_cache() -> None:
    _cache.clear()


def buscar_tenant(slug: str) -> Optional[TenantInfo]:
    """Busca una empresa activa por subdominio (con una caché corta, para no consultar en cada petición)."""
    if not _PATRON_SLUG.match(slug or ""):
        return None
    hit = _cache.get(slug)
    if hit and time.time() - hit[0] < _TTL_CACHE_SEGUNDOS:
        return hit[1]
    db = SessionLocal()
    try:
        fila = db.query(Tenant).filter(Tenant.subdominio == slug, Tenant.activo.is_(True)).first()
        info = a_info(fila) if fila else None
    finally:
        db.close()
    _cache[slug] = (time.time(), info)
    return info


def listar_tenants(solo_activos: bool = True) -> list:
    db = SessionLocal()
    try:
        q = db.query(Tenant)
        if solo_activos:
            q = q.filter(Tenant.activo.is_(True))
        return [a_info(t) for t in q.order_by(Tenant.subdominio).all()]
    finally:
        db.close()


def slug_de_peticion(request: Request) -> Optional[str]:
    """Empresa de la petición: encabezado X-Tenant (frontend en otro dominio), o subdominio del Host,
    o la empresa por defecto de la instalación."""
    explicito = (request.headers.get("x-tenant") or "").strip().lower()
    if explicito:
        return explicito
    host = (request.headers.get("host") or "").split(":")[0].lower()
    base = config.BASE_DOMAIN
    if base and host.endswith("." + base):
        return host[: -len(base) - 1]
    return config.TENANT_POR_DEFECTO or None


def obtener_tenant_opcional(request: Request) -> Optional[TenantInfo]:
    slug = slug_de_peticion(request)
    return buscar_tenant(slug) if slug else None


def obtener_tenant(request: Request) -> TenantInfo:
    if not slug_de_peticion(request):
        raise HTTPException(status_code=404, detail="No se indicó la empresa (subdominio)")
    tenant = obtener_tenant_opcional(request)
    if not tenant:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return tenant


def get_db(tenant: TenantInfo = Depends(obtener_tenant)):
    db = sesion_tenant(tenant.esquema)
    try:
        yield db
    finally:
        db.close()
