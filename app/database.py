import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# En Neon, la URL viene del dashboard: Connect > Connection string
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@host/dbname")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 10},  # si no conecta en 10s, falla con error claro (no se cuelga)
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Modelos de cada empresa: las mismas tablas se crean en un esquema propio por empresa.
Base = declarative_base()
# Registro de empresas y control de la plataforma: viven en el esquema "public".
ControlBase = declarative_base()


def sesion_tenant(esquema: str):
    """Sesión cuyas tablas (sin esquema explícito) se resuelven dentro del esquema de la empresa.
    Se hace con schema_translate_map, no con SET search_path, para no dejar estado en las conexiones del pool."""
    return SessionLocal(bind=engine.execution_options(schema_translate_map={None: esquema}))


def engine_tenant(esquema: str):
    return engine.execution_options(schema_translate_map={None: esquema})
