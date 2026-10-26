"""
Prepara una instalación nueva: crea las tablas, la organización y el primer administrador,
y opcionalmente carga un catálogo de tipos de trámite desde un CSV.

    python -m app.seed --organizacion "Mi Empresa" --nombre "Ana Pérez" \\
        --email ana@miempresa.com --password "una-clave-larga" \\
        --catalogo datos/catalogo_ejemplo.csv
"""
import argparse
import csv
import sys

from . import auth, models
from .database import Base, SessionLocal, engine


def _lista(valor: str) -> list:
    return [x.strip() for x in (valor or "").split("|") if x.strip()]


def cargar_catalogo(db, ruta: str) -> int:
    creados = 0
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        for fila in csv.DictReader(f):
            categoria = (fila.get("categoria") or "").strip().lower()
            nombre = (fila.get("nombre") or "").strip()
            if not categoria or not nombre:
                continue
            existe = (
                db.query(models.TipoTramite)
                .filter(models.TipoTramite.categoria == categoria, models.TipoTramite.nombre == nombre)
                .first()
            )
            if existe:
                continue
            vigencia = (fila.get("vigencia_meses") or "").strip()
            db.add(models.TipoTramite(
                categoria=categoria,
                nombre=nombre,
                institucion=(fila.get("institucion") or "").strip() or None,
                tipo_gestion=(fila.get("tipo_gestion") or "").strip() or None,
                vigencia_meses=int(vigencia) if vigencia else None,
                vigencia_desde=(fila.get("vigencia_desde") or "aprobacion").strip() or "aprobacion",
                etapas=_lista(fila.get("etapas")),
                checklist_default=_lista(fila.get("checklist")),
            ))
            creados += 1
    return creados


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--organizacion", required=True, help="Nombre de la empresa que usará el sistema")
    parser.add_argument("--nombre", required=True, help="Nombre del primer administrador")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True, help="Mínimo 8 caracteres")
    parser.add_argument("--catalogo", help="CSV con tipos de trámite (ver datos/catalogo_ejemplo.csv)")
    args = parser.parse_args()

    if len(args.password) < 8:
        sys.exit("La contraseña debe tener al menos 8 caracteres.")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(models.Usuario).filter(models.Usuario.email == args.email).first():
            sys.exit(f"Ya existe un usuario con el correo {args.email}.")

        org = db.query(models.Organizacion).first()
        if not org:
            org = models.Organizacion(nombre=args.organizacion)
            db.add(org)
            db.flush()
        db.add(models.Usuario(
            organizacion_id=org.id,
            nombre=args.nombre,
            email=args.email,
            password_hash=auth.hash_password(args.password),
            rol="admin",
        ))
        tipos = cargar_catalogo(db, args.catalogo) if args.catalogo else 0
        db.commit()
        print(f"Listo: organización '{org.nombre}', administrador {args.email}, {tipos} tipos de trámite cargados.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
