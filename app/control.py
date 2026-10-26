import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from .database import ControlBase


class Tenant(ControlBase):
    """Una empresa de la plataforma: su subdominio, su esquema de datos y su marca."""
    __tablename__ = "tenant"
    __table_args__ = {"schema": "public"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subdominio = Column(String(63), nullable=False, unique=True)
    esquema = Column(String(63), nullable=False, unique=True)
    nombre = Column(String(200), nullable=False)
    activo = Column(Boolean, nullable=False, default=True)
    # Marca; lo que no se defina usa los valores por defecto de la instalación (APP_NAME, etc.)
    nombre_app = Column(String(100), nullable=True)
    eslogan = Column(String(250), nullable=True)
    color_primario = Column(String(7), nullable=True)
    logo_url = Column(String(500), nullable=True)
    correo_alertas = Column(String(200), nullable=True)
    creado_en = Column(DateTime(timezone=True), default=datetime.utcnow)


class MigracionAplicada(ControlBase):
    __tablename__ = "migracion_aplicada"
    __table_args__ = {"schema": "public"}
    esquema = Column(String(63), primary_key=True)
    archivo = Column(String(200), primary_key=True)
    aplicada_en = Column(DateTime(timezone=True), default=datetime.utcnow)


class AdminPlataforma(ControlBase):
    """Quien administra la plataforma (crea y configura empresas). No pertenece a ninguna empresa."""
    __tablename__ = "admin_plataforma"
    __table_args__ = {"schema": "public"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(150), nullable=False)
    email = Column(String(200), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    activo = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime(timezone=True), default=datetime.utcnow)
