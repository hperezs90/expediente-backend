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
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
