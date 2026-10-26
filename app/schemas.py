from datetime import date, datetime
from typing import Optional, List, Dict
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class EmpresaClienteBase(BaseModel):
    nombre: str
    nit: Optional[str] = None  # ID fiscal (NIT, RFC, RUT, EIN, etc.)
    contacto_nombre: Optional[str] = None
    contacto_email: Optional[EmailStr] = None
    contacto_telefono: Optional[str] = None
    notas: Optional[str] = None


class EmpresaClienteCreate(EmpresaClienteBase):
    pass


class EmpresaClienteOut(EmpresaClienteBase):
    id: UUID
    creado_en: datetime

    class Config:
        from_attributes = True


class EmpresaClienteUpdate(BaseModel):
    nombre: Optional[str] = None
    nit: Optional[str] = None
    contacto_nombre: Optional[str] = None
    contacto_email: Optional[EmailStr] = None
    contacto_telefono: Optional[str] = None
    notas: Optional[str] = None


class TramiteBase(BaseModel):
    empresa_cliente_id: UUID
    tipo_tramite_id: UUID
    asignado_a: Optional[UUID] = None
    numero_expediente: Optional[str] = None
    fecha_inicio: date
    fecha_vencimiento: Optional[date] = None
    estado: str = "en_tramite"
    notas: Optional[str] = None
    anticipo: Optional[str] = None
    complemento: Optional[str] = None
    descripcion: Optional[str] = None
    numero_registro: Optional[str] = None


class TramiteCreate(TramiteBase):
    pass


class TramiteOut(TramiteBase):
    id: UUID
    checklist: List[dict] = []
    creado_en: datetime

    class Config:
        from_attributes = True


class TipoTramiteOut(BaseModel):
    id: UUID
    categoria: str
    nombre: str
    institucion: Optional[str]
    tipo_gestion: Optional[str]
    vigencia_meses: Optional[int]
    vigencia_desde: str = "aprobacion"
    etapas: List[str] = []
    es_recurrente: bool
    frecuencia_dias: Optional[int] = None
    checklist_default: List[str] = []
    notas: Optional[str] = None
    activo: bool = True
    tramites_asociados: int = 0

    class Config:
        from_attributes = True


class TipoTramiteBase(BaseModel):
    categoria: str
    nombre: str
    institucion: Optional[str] = None
    tipo_gestion: Optional[str] = None
    vigencia_meses: Optional[int] = None
    vigencia_desde: str = Field("aprobacion", pattern="^(inicio|aprobacion)$")
    etapas: List[str] = []
    es_recurrente: bool = False
    frecuencia_dias: Optional[int] = None
    checklist_default: List[str] = []
    notas: Optional[str] = None
    activo: bool = True


class TipoTramiteCreate(TipoTramiteBase):
    pass


class TipoTramiteUpdate(BaseModel):
    categoria: Optional[str] = None
    nombre: Optional[str] = None
    institucion: Optional[str] = None
    tipo_gestion: Optional[str] = None
    vigencia_meses: Optional[int] = None
    vigencia_desde: Optional[str] = Field(None, pattern="^(inicio|aprobacion)$")
    etapas: Optional[List[str]] = None
    es_recurrente: Optional[bool] = None
    frecuencia_dias: Optional[int] = None
    checklist_default: Optional[List[str]] = None
    notas: Optional[str] = None
    activo: Optional[bool] = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UsuarioOut(BaseModel):
    id: UUID
    nombre: str
    email: EmailStr
    rol: str
    activo: bool = True
    organizacion_nombre: Optional[str] = None

    class Config:
        from_attributes = True


class UsuarioCreate(BaseModel):
    nombre: str
    email: EmailStr
    password: str
    rol: str = "gestor"


class UsuarioUpdate(BaseModel):
    nombre: Optional[str] = None
    rol: Optional[str] = None
    activo: Optional[bool] = None


class UsuarioPasswordUpdate(BaseModel):
    password: str = Field(min_length=8)


class AsignacionEmpresas(BaseModel):
    usuario_ids: List[UUID]


class DashboardResumen(BaseModel):
    total_empresas: int
    empresas_sin_tramites: int


class TramiteDashboardOut(BaseModel):
    id: UUID
    empresa_id: UUID
    empresa_nombre: str
    tramite_nombre: str
    categoria: str
    numero_expediente: Optional[str] = None
    descripcion: Optional[str] = None
    renovado: bool = False  # ya existe un trámite que lo renueva
    fecha_vencimiento: Optional[date] = None
    estado: str
    creado_por_nombre: Optional[str] = None
    asignado_a_nombre: Optional[str] = None
    estatus_calculado: Optional[str] = None
    creado_en: datetime
    fecha_limite_observacion: Optional[date] = None


class ImportacionError(BaseModel):
    fila: int
    motivo: str


class ImportacionResultado(BaseModel):
    total_filas: int
    creados: int
    empresas_creadas: int
    errores: List[ImportacionError]


class DocumentoOut(BaseModel):
    id: UUID
    tipo: str
    nombre_archivo: str
    tamano_bytes: Optional[int] = None
    version: int = 1
    subido_por_nombre: Optional[str] = None
    creado_en: datetime
    url_descarga: Optional[str] = None
    observacion_id: Optional[UUID] = None


class AuditoriaOut(BaseModel):
    campo: str
    valor_anterior: Optional[str] = None
    valor_nuevo: Optional[str] = None
    usuario_nombre: Optional[str] = None
    creado_en: datetime
    tramite_nombre: Optional[str] = None


class ObservacionBase(BaseModel):
    fecha_emision: Optional[date] = None
    motivo: Optional[str] = None
    fecha_vencimiento: Optional[date] = None
    fecha_respuesta: Optional[date] = None


class ObservacionCreate(ObservacionBase):
    numero: Optional[int] = None  # si no se envía, se asigna el siguiente


class ObservacionUpdate(ObservacionBase):
    pass


class ObservacionOut(ObservacionBase):
    id: UUID
    numero: int

    class Config:
        from_attributes = True


class TramiteUpdate(BaseModel):
    numero_expediente: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    estado: Optional[str] = None
    notas: Optional[str] = None
    checklist: Optional[List[dict]] = None
    asignado_a: Optional[UUID] = None
    resolucion_final: Optional[str] = None
    fecha_aprobacion: Optional[date] = None
    etapas_fechas: Optional[Dict[str, Optional[date]]] = None
    anticipo: Optional[str] = None
    complemento: Optional[str] = None
    descripcion: Optional[str] = None
    numero_registro: Optional[str] = None


class TramiteEmpresaOut(BaseModel):
    id: UUID
    tramite_nombre: str
    categoria: str
    vigencia_meses: Optional[int] = None
    vigencia_desde: str = "aprobacion"
    etapas: List[str] = []
    numero_expediente: Optional[str] = None
    fecha_inicio: date
    fecha_vencimiento: Optional[date] = None
    estado: str
    checklist: List[dict] = []
    creado_por_nombre: Optional[str] = None
    asignado_a: Optional[UUID] = None
    asignado_a_nombre: Optional[str] = None
    resolucion_final: Optional[str] = None
    fecha_aprobacion: Optional[date] = None
    etapas_fechas: Dict[str, Optional[date]] = {}
    renueva_a_id: Optional[UUID] = None
    renovado_por_id: Optional[UUID] = None
    anticipo: Optional[str] = None
    complemento: Optional[str] = None
    descripcion: Optional[str] = None
    numero_registro: Optional[str] = None
    documentos: List[DocumentoOut] = []
    observaciones: List[ObservacionOut] = []
    estatus_calculado: Optional[str] = None


class RenovarTramite(BaseModel):
    fecha_inicio: Optional[date] = None  # por defecto, hoy


class ConfigPublica(BaseModel):
    app_name: str
    tagline: str
    primary_color: str
    logo_url: str
    inactividad_minutos: int
    plazo_observacion_meses: int
    ventana_renovacion_dias: int
    dominio_base: str = ""


class IntentoLoginOut(BaseModel):
    id: UUID
    email_intentado: str
    ip: Optional[str] = None
    exitoso: bool
    creado_en: datetime

    class Config:
        from_attributes = True
