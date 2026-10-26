import uuid
from datetime import date, datetime

from sqlalchemy import (
    Column, String, Boolean, Integer, Date, DateTime, ForeignKey, Text, JSON, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, backref

from .database import Base


class Organizacion(Base):
    __tablename__ = "organizacion"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(200), nullable=False)
    creado_en = Column(DateTime(timezone=True), default=datetime.utcnow)

    usuarios = relationship("Usuario", back_populates="organizacion")
    empresas = relationship("EmpresaCliente", back_populates="organizacion")


class Usuario(Base):
    __tablename__ = "usuario"
    __table_args__ = (CheckConstraint("rol IN ('admin','gestor')", name="usuario_rol_check"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organizacion_id = Column(UUID(as_uuid=True), ForeignKey("organizacion.id"), nullable=False)
    nombre = Column(String(150), nullable=False)
    email = Column(String(200), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    rol = Column(String(20), nullable=False)  # 'admin' | 'gestor'
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime(timezone=True), default=datetime.utcnow)

    organizacion = relationship("Organizacion", back_populates="usuarios")

    @property
    def organizacion_nombre(self):
        return self.organizacion.nombre if self.organizacion else None


class EmpresaCliente(Base):
    __tablename__ = "empresa_cliente"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organizacion_id = Column(UUID(as_uuid=True), ForeignKey("organizacion.id"), nullable=False)
    nombre = Column(String(250), nullable=False)
    nit = Column(String(30))
    contacto_nombre = Column(String(150))
    contacto_email = Column(String(200))
    contacto_telefono = Column(String(30))
    notas = Column(Text)
    creado_en = Column(DateTime(timezone=True), default=datetime.utcnow)

    organizacion = relationship("Organizacion", back_populates="empresas")
    tramites = relationship("Tramite", back_populates="empresa_cliente")


class TipoTramite(Base):
    __tablename__ = "tipo_tramite"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    categoria = Column(String(50), nullable=False)  # texto libre, definido por cada organización (ej. "ambiente", "laboral")
    nombre = Column(String(250), nullable=False)
    institucion = Column(String(100))  # entidad ante la que se gestiona
    tipo_gestion = Column(String(100))
    vigencia_meses = Column(Integer, nullable=True)
    vigencia_desde = Column(String(10), default="aprobacion")  # 'inicio' | 'aprobacion': desde cuándo cuenta la vigencia
    etapas = Column(JSON, default=list)  # etapas del flujo interno, en orden (ej. ["Firma", "Presentado"])
    es_recurrente = Column(Boolean, default=False)
    frecuencia_dias = Column(Integer, nullable=True)
    checklist_default = Column(JSON, default=list)
    notas = Column(Text)
    activo = Column(Boolean, default=True)  # false = retirado del catálogo; no aparece para trámites nuevos, pero los existentes lo conservan


class Tramite(Base):
    __tablename__ = "tramite"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('en_tramite','vigente','por_vencer','vencido','renovacion_en_curso')",
            name="tramite_estado_check",
        ),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_cliente_id = Column(UUID(as_uuid=True), ForeignKey("empresa_cliente.id"), nullable=False)
    tipo_tramite_id = Column(UUID(as_uuid=True), ForeignKey("tipo_tramite.id"), nullable=False)
    asignado_a = Column(UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True)
    creado_por_id = Column(UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True)
    numero_expediente = Column(String(100))
    fecha_inicio = Column(Date, nullable=False, default=date.today)
    fecha_vencimiento = Column(Date, nullable=True)
    estado = Column(String(20), default="en_tramite")
    checklist = Column(JSON, default=list)
    notas = Column(Text)

    resolucion_final = Column(String(20), nullable=True)     # aprobado | rechazado | finalizado | pendiente
    fecha_aprobacion = Column(Date, nullable=True)            # fecha real de aprobación; si el tipo cuenta la vigencia desde aquí, el vencimiento se calcula de esta fecha
    etapas_fechas = Column(JSON, default=dict)                # {nombre_etapa: "YYYY-MM-DD"}, según las etapas definidas en el tipo de trámite

    # Si este trámite es la renovación (o el siguiente periodo) de otro, apunta al original
    renueva_a_id = Column(UUID(as_uuid=True), ForeignKey("tramite.id", ondelete="SET NULL"), nullable=True, index=True)

    # Identifica de qué se trata (producto, sede, equipo, etc.)
    descripcion = Column(Text, nullable=True)
    numero_registro = Column(String(100), nullable=True)  # número final de registro/licencia/resolución (no el de expediente de seguimiento)
    # (el vencimiento usa el fecha_vencimiento general que ya existe)

    # Seguimiento de pagos (aplica a cualquier categoría)
    anticipo = Column(Text, nullable=True)
    complemento = Column(Text, nullable=True)

    creado_en = Column(DateTime(timezone=True), default=datetime.utcnow)
    actualizado_en = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    empresa_cliente = relationship("EmpresaCliente", back_populates="tramites")
    tipo_tramite = relationship("TipoTramite")
    creado_por = relationship("Usuario", foreign_keys=[creado_por_id])
    asignado_a_usuario = relationship("Usuario", foreign_keys=[asignado_a])
    observaciones = relationship("Observacion", back_populates="tramite", order_by="Observacion.numero", cascade="all, delete-orphan")
    documentos = relationship("Documento", order_by="Documento.creado_en.desc()", cascade="all, delete-orphan")
    renovaciones = relationship("Tramite", foreign_keys=[renueva_a_id], backref=backref("renueva_a", remote_side=[id]))


class Observacion(Base):
    """Requerimiento o rechazo parcial de la entidad que debe responderse dentro de un plazo."""
    __tablename__ = "observacion"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tramite_id = Column(UUID(as_uuid=True), ForeignKey("tramite.id", ondelete="CASCADE"), nullable=False)
    numero = Column(Integer, nullable=False)

    fecha_emision = Column(Date, nullable=True)
    motivo = Column(Text, nullable=True)
    fecha_vencimiento = Column(Date, nullable=True)  # plazo para responder — aquí aplican las alertas
    fecha_respuesta = Column(Date, nullable=True)    # cuándo se respondió a la entidad

    creado_en = Column(DateTime(timezone=True), default=datetime.utcnow)

    tramite = relationship("Tramite", back_populates="observaciones")


class UsuarioEmpresaCliente(Base):
    __tablename__ = "usuario_empresa_cliente"
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuario.id"), primary_key=True)
    empresa_cliente_id = Column(UUID(as_uuid=True), ForeignKey("empresa_cliente.id"), primary_key=True)


class Documento(Base):
    __tablename__ = "documento"
    __table_args__ = (
        CheckConstraint("tipo IN ('ingreso','resolucion','observacion','otro')", name="documento_tipo_valido"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tramite_id = Column(UUID(as_uuid=True), ForeignKey("tramite.id", ondelete="CASCADE"), nullable=False)
    observacion_id = Column(UUID(as_uuid=True), ForeignKey("observacion.id", ondelete="CASCADE"), nullable=True)
    tipo = Column(String(30), nullable=False)  # ingreso | resolucion | observacion | otro
    nombre_archivo = Column(Text, nullable=False)
    clave_almacenamiento = Column(Text, nullable=False)
    tamano_bytes = Column(Integer, nullable=True)
    version = Column(Integer, nullable=False, default=1)  # por (trámite, tipo, observación): 1, 2, 3...
    subido_por_id = Column(UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True)
    creado_en = Column(DateTime(timezone=True), default=datetime.utcnow)

    subido_por = relationship("Usuario")


class AuditoriaTramite(Base):
    __tablename__ = "auditoria_tramite"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tramite_id = Column(UUID(as_uuid=True), nullable=False)  # sin FK: debe sobrevivir al borrado del trámite
    empresa_id = Column(UUID(as_uuid=True), nullable=True)
    empresa_nombre = Column(Text, nullable=True)
    tramite_nombre = Column(Text, nullable=True)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True)
    campo = Column(String(50), nullable=False)
    valor_anterior = Column(Text, nullable=True)
    valor_nuevo = Column(Text, nullable=True)
    creado_en = Column(DateTime(timezone=True), default=datetime.utcnow)

    usuario = relationship("Usuario")


class Alerta(Base):
    __tablename__ = "alerta"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tramite_id = Column(UUID(as_uuid=True), ForeignKey("tramite.id"), nullable=False)
    observacion_id = Column(UUID(as_uuid=True), ForeignKey("observacion.id", ondelete="CASCADE"), nullable=True)
    dias_previos = Column(Integer, nullable=False)
    fecha_programada = Column(Date, nullable=False)
    enviada = Column(Boolean, default=False)
    enviada_en = Column(DateTime(timezone=True), nullable=True)
    canal = Column(String(20), default="email")
    creado_en = Column(DateTime(timezone=True), default=datetime.utcnow)


class IntentoLogin(Base):
    __tablename__ = "intento_login"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_intentado = Column(String(200), nullable=False)
    ip = Column(String(64), nullable=True)
    exitoso = Column(Boolean, nullable=False)
    creado_en = Column(DateTime(timezone=True), default=datetime.utcnow)
    # Nunca se guarda la contraseña, ni siquiera con hash — no hace falta para auditar el patrón de intentos.
