"""
Administración de empresas (tenants): cada empresa tiene un subdominio y su propio esquema de PostgreSQL.

    python -m app.tenants crear --subdominio acme --nombre "Acme S.A." \\
        --admin-nombre "Ana Pérez" --admin-email ana@acme.com --admin-password "una-clave-larga" \\
        --catalogo datos/catalogo_ejemplo.csv
    python -m app.tenants listar
    python -m app.tenants crear-superadmin --nombre "Ana" --email ana@miapp.com --password "una-clave-larga"
    python -m app.tenants adoptar --subdominio acme      # mueve a una empresa las tablas que estén en "public"
    python -m app.tenants migrar                         # aplica migrations/*.sql pendientes a cada empresa
    python -m app.tenants desactivar --subdominio acme   # (o: activar)
"""
import argparse
import csv
import glob
import os
import sys

from sqlalchemy import inspect, text

from . import auth, models, tenancy
from . import config
from .control import AdminPlataforma, MigracionAplicada, Tenant
from .database import Base, ControlBase, SessionLocal, engine, engine_tenant, sesion_tenant

DIR_MIGRACIONES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")


class ErrorTenant(Exception):
    pass


def asegurar_tablas_control() -> None:
    ControlBase.metadata.create_all(bind=engine)


def guardar_admin_plataforma(nombre: str, email: str, password: str) -> bool:
    """Crea un administrador de la plataforma, o cambia su contraseña si el correo ya existe. True si se creó."""
    if len(password) < 8:
        raise ErrorTenant("La contraseña debe tener al menos 8 caracteres.")
    asegurar_tablas_control()
    db = SessionLocal()
    try:
        a = db.query(AdminPlataforma).filter(AdminPlataforma.email == email).first()
        creado = a is None
        if creado:
            a = AdminPlataforma(nombre=nombre, email=email, password_hash="")
            db.add(a)
        a.nombre = nombre
        a.activo = True
        a.password_hash = auth.hash_password(password)
        db.commit()
        return creado
    finally:
        db.close()


def asegurar_admin_inicial() -> None:
    """Si no hay ningún administrador de plataforma y se definieron PLATAFORMA_ADMIN_EMAIL/PASSWORD, lo crea."""
    if not (config.PLATAFORMA_ADMIN_EMAIL and len(config.PLATAFORMA_ADMIN_PASSWORD) >= 8):
        return
    db = SessionLocal()
    try:
        hay = db.query(AdminPlataforma).first() is not None
    finally:
        db.close()
    if not hay:
        guardar_admin_plataforma("Administrador", config.PLATAFORMA_ADMIN_EMAIL, config.PLATAFORMA_ADMIN_PASSWORD)


def _archivos_migracion() -> list:
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(DIR_MIGRACIONES, "*.sql")))


def _lista(valor: str) -> list:
    return [x.strip() for x in (valor or "").split("|") if x.strip()]


def cargar_catalogo(db, ruta: str) -> int:
    """Carga tipos de trámite desde un CSV (ver datos/catalogo_ejemplo.csv). Ignora los que ya existen."""
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


def _validar_slug(subdominio: str) -> str:
    slug = (subdominio or "").strip().lower()
    if not tenancy.slug_valido(slug):
        raise ErrorTenant(
            f"Subdominio inválido o reservado: '{subdominio}'. Usa letras minúsculas, números y guiones (2 a 42 caracteres)."
        )
    return slug


def _registrar_migraciones_como_aplicadas(esquema: str) -> None:
    db = SessionLocal()
    try:
        for archivo in _archivos_migracion():
            db.merge(MigracionAplicada(esquema=esquema, archivo=archivo))
        db.commit()
    finally:
        db.close()


def provisionar(
    subdominio: str,
    nombre: str,
    admin_nombre: str,
    admin_email: str,
    admin_password: str,
    catalogo: str | None = None,
    **marca,
) -> tenancy.TenantInfo:
    """Crea la empresa: esquema + tablas + registro + organización + primer administrador (+ catálogo opcional)."""
    if len(admin_password) < 8:
        raise ErrorTenant("La contraseña debe tener al menos 8 caracteres.")
    slug = _validar_slug(subdominio)
    esquema = tenancy.esquema_de(slug)
    asegurar_tablas_control()

    db = SessionLocal()
    try:
        if db.query(Tenant).filter((Tenant.subdominio == slug) | (Tenant.esquema == esquema)).first():
            raise ErrorTenant(f"Ya existe una empresa con el subdominio '{slug}'.")
    finally:
        db.close()

    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{esquema}"'))
    try:
        Base.metadata.create_all(bind=engine_tenant(esquema))

        db = SessionLocal()
        try:
            registro = Tenant(subdominio=slug, esquema=esquema, nombre=nombre, **marca)
            db.add(registro)
            db.commit()
            db.refresh(registro)
            info = tenancy.a_info(registro)
        finally:
            db.close()

        sesion = sesion_tenant(esquema)
        try:
            org = models.Organizacion(nombre=nombre)
            sesion.add(org)
            sesion.flush()
            sesion.add(models.Usuario(
                organizacion_id=org.id,
                nombre=admin_nombre,
                email=admin_email,
                password_hash=auth.hash_password(admin_password),
                rol="admin",
            ))
            if catalogo:
                cargar_catalogo(sesion, catalogo)
            sesion.commit()
        finally:
            sesion.close()
        _registrar_migraciones_como_aplicadas(esquema)
    except Exception:
        # Si algo falla a medias, no se deja un esquema ni un registro huérfanos
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{esquema}" CASCADE'))
            conn.execute(text("DELETE FROM public.tenant WHERE esquema = :e"), {"e": esquema})
        raise
    tenancy.invalidar_cache()
    return info


def adoptar(subdominio: str, nombre: str | None = None) -> tenancy.TenantInfo:
    """Convierte una instalación de una sola empresa (tablas en "public") en una empresa de la plataforma,
    moviendo sus tablas a un esquema propio. No copia datos: solo las cambia de esquema."""
    slug = _validar_slug(subdominio)
    esquema = tenancy.esquema_de(slug)
    asegurar_tablas_control()
    insp = inspect(engine)
    tablas = [t for t in Base.metadata.tables if insp.has_table(t, schema="public")]
    if "organizacion" not in tablas:
        raise ErrorTenant("No hay una instalación de una sola empresa en el esquema 'public' para adoptar.")

    db = SessionLocal()
    try:
        if db.query(Tenant).filter((Tenant.subdominio == slug) | (Tenant.esquema == esquema)).first():
            raise ErrorTenant(f"Ya existe una empresa con el subdominio '{slug}'.")
        if not nombre:
            nombre = db.execute(text("SELECT nombre FROM public.organizacion LIMIT 1")).scalar() or slug
    finally:
        db.close()

    with engine.begin() as conn:  # una sola transacción: o se mueve todo o nada
        conn.execute(text(f'CREATE SCHEMA "{esquema}"'))
        for t in tablas:
            conn.execute(text(f'ALTER TABLE public."{t}" SET SCHEMA "{esquema}"'))
        conn.execute(text(
            "INSERT INTO public.tenant (id, subdominio, esquema, nombre, activo, creado_en) "
            "VALUES (gen_random_uuid(), :s, :e, :n, true, now())"
        ), {"s": slug, "e": esquema, "n": nombre})
    # Tablas que el modelo tenga y la instalación vieja no (si las hay)
    Base.metadata.create_all(bind=engine_tenant(esquema))
    _registrar_migraciones_como_aplicadas(esquema)
    tenancy.invalidar_cache()
    return tenancy.buscar_tenant(slug)


def migrar() -> list:
    """Aplica a cada empresa los archivos de migrations/ que todavía no tenga. Devuelve lo aplicado."""
    asegurar_tablas_control()
    aplicadas = []
    for t in tenancy.listar_tenants(solo_activos=False):
        db = SessionLocal()
        try:
            hechas = {m.archivo for m in db.query(MigracionAplicada).filter(MigracionAplicada.esquema == t.esquema)}
        finally:
            db.close()
        for archivo in _archivos_migracion():
            if archivo in hechas:
                continue
            with open(os.path.join(DIR_MIGRACIONES, archivo), encoding="utf-8") as f:
                sql = f.read()
            raw = engine.raw_connection()
            try:
                raw.autocommit = True  # los archivos traen su propio BEGIN/COMMIT
                cur = raw.cursor()
                cur.execute(f'SET search_path TO "{t.esquema}"')
                cur.execute(sql)
                cur.execute("RESET search_path")
            finally:
                raw.close()
            db = SessionLocal()
            try:
                db.add(MigracionAplicada(esquema=t.esquema, archivo=archivo))
                db.commit()
            finally:
                db.close()
            aplicadas.append((t.subdominio, archivo))
    return aplicadas


def cambiar_activo(subdominio: str, activo: bool) -> None:
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter(Tenant.subdominio == subdominio.strip().lower()).first()
        if not t:
            raise ErrorTenant(f"No existe la empresa '{subdominio}'.")
        t.activo = activo
        db.commit()
    finally:
        db.close()
    tenancy.invalidar_cache()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("crear", help="Crea una empresa nueva")
    c.add_argument("--subdominio", required=True)
    c.add_argument("--nombre", required=True, help="Nombre de la empresa")
    c.add_argument("--admin-nombre", required=True)
    c.add_argument("--admin-email", required=True)
    c.add_argument("--admin-password", required=True, help="Mínimo 8 caracteres")
    c.add_argument("--catalogo", help="CSV con tipos de trámite (ver datos/catalogo_ejemplo.csv)")
    c.add_argument("--color", help="Color principal, ej. #2e7d4f")
    c.add_argument("--logo-url")
    c.add_argument("--correo-alertas")

    sub.add_parser("listar", help="Lista las empresas")

    sa = sub.add_parser("crear-superadmin", help="Crea un administrador de la plataforma (o cambia su contraseña)")
    sa.add_argument("--nombre", required=True)
    sa.add_argument("--email", required=True)
    sa.add_argument("--password", required=True, help="Mínimo 8 caracteres")

    a = sub.add_parser("adoptar", help="Convierte las tablas de 'public' en una empresa")
    a.add_argument("--subdominio", required=True)
    a.add_argument("--nombre")

    sub.add_parser("migrar", help="Aplica las migraciones pendientes a todas las empresas")
    for nombre in ("activar", "desactivar"):
        s = sub.add_parser(nombre)
        s.add_argument("--subdominio", required=True)

    args = parser.parse_args()
    try:
        if args.cmd == "crear":
            marca = {k: v for k, v in {
                "color_primario": args.color, "logo_url": args.logo_url, "correo_alertas": args.correo_alertas,
            }.items() if v}
            t = provisionar(args.subdominio, args.nombre, args.admin_nombre, args.admin_email,
                            args.admin_password, args.catalogo, **marca)
            print(f"Listo: empresa '{t.nombre}' en el subdominio '{t.subdominio}' (esquema {t.esquema}).")
        elif args.cmd == "listar":
            asegurar_tablas_control()
            for t in tenancy.listar_tenants(solo_activos=False):
                print(f"{t.subdominio:<24}{t.esquema:<28}{'activa' if t.activo else 'INACTIVA':<10}{t.nombre}")
        elif args.cmd == "crear-superadmin":
            creado = guardar_admin_plataforma(args.nombre, args.email, args.password)
            print(f"Listo: administrador de la plataforma {'creado' if creado else 'actualizado'} ({args.email}).")
        elif args.cmd == "adoptar":
            t = adoptar(args.subdominio, args.nombre)
            print(f"Listo: las tablas de 'public' ahora son la empresa '{t.nombre}' ({t.subdominio}).")
        elif args.cmd == "migrar":
            hechas = migrar()
            print("\n".join(f"{s}: {a}" for s, a in hechas) or "Todas las empresas están al día.")
        else:
            cambiar_activo(args.subdominio, args.cmd == "activar")
            print("Listo.")
    except ErrorTenant as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
