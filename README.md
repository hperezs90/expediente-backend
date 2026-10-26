# Expediente — Backend

Sistema para dar seguimiento a **trámites, permisos y licencias** de una o varias empresas:
vencimientos con alertas por correo, flujo por etapas, observaciones de la entidad con plazo de
respuesta, documentos, checklist, historial de cambios y asignación por gestor.

Es genérico: cada instalación define su propio catálogo (categorías, tipos de trámite, vigencias
y etapas), su nombre, color y logo. El frontend vive en el repo `Registros-frontend`.

## Conceptos

| Concepto | Qué es |
|---|---|
| **Empresa** | A quien pertenecen los trámites (tu propia empresa, sus sedes o tus clientes). |
| **Tipo de trámite** (catálogo) | Plantilla: categoría, entidad, vigencia en meses, desde cuándo cuenta (inicio o aprobación), etapas del flujo y checklist. |
| **Trámite** | Una gestión concreta de una empresa: fechas, etapas cumplidas, resolución, vencimiento. |
| **Etapas** | Pasos que defines por tipo (ej. *Preparación → Firma → Presentado → En revisión*). El estatus muestra la última etapa con fecha. |
| **Observación** | Requerimiento de la entidad con plazo para responder; genera alertas hasta que se registra la respuesta. |
| **Roles** | `admin` (todo) y `gestor` (solo las empresas que tiene asignadas). |

## Instalación

Requisitos: Python 3.11+ y PostgreSQL.

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # edita DATABASE_URL y SECRET_KEY
export $(grep -v '^#' .env | xargs) # la app lee variables de entorno (no carga .env sola)
```

Crea las tablas, tu empresa, el primer administrador y, opcionalmente, un catálogo inicial:

```bash
python -m app.seed --organizacion "Mi Empresa" --nombre "Ana Pérez" \
    --email ana@miempresa.com --password "una-clave-larga" \
    --catalogo datos/catalogo_ejemplo.csv
```

Arranca el servidor:

```bash
uvicorn app.main:app --reload
```

Documentación interactiva en http://localhost:8000/docs. `schema.sql` contiene el esquema por si
prefieres crearlo a mano (`psql "$DATABASE_URL" -f schema.sql`).

### Catálogo inicial

`datos/catalogo_ejemplo.csv` muestra el formato (`etapas` y `checklist` separados por `|`).
Copia y edítalo con tus propios trámites, o créalos desde la pantalla **Catálogo** del sistema.

### Documentos y versiones

Se aceptan PDF, JPG y PNG (hasta 15 MB); desde el celular se puede tomar la foto directamente y se
reduce antes de subirla. Cada subida nueva del mismo documento queda como una versión más y las
anteriores se conservan como historial. Los archivos se guardan en `STORAGE_DIR` (o en S3/B2) y se
descargan con enlaces firmados que vencen en una hora. **Respalda esa carpeta junto con la base de datos.**

### Migrar una base del sistema original

Si vienes de la versión anterior (con Ambiente/Alimentos/Farma, "reparos" y campos fijos), ejecuta
**una vez**, en orden, `migrations/001_generico.sql` y `migrations/002_version_documentos.sql` (`psql "$DATABASE_URL" -f ...`). Conserva los datos: las fechas de
los flujos viejos pasan a las etapas del catálogo y los reparos pasan a observaciones. Haz un respaldo antes.

## Configuración (variables de entorno)

Ver `.env.example`. Lo más relevante:

- `APP_NAME`, `APP_TAGLINE`, `APP_PRIMARY_COLOR`, `APP_LOGO_URL`: identidad visual (el frontend las lee de `GET /config`).
- `PLAZO_OBSERVACION_MESES`: plazo para responder una observación (por defecto 3).
- `UMBRALES_VENCIMIENTO` / `UMBRALES_OBSERVACION`: días previos en los que se envían alertas.
- `INACTIVIDAD_MINUTOS`: cierre de sesión automático (0 = desactivado).
- `RESEND_API_KEY`, `ALERT_FROM_EMAIL`, `CORREO_UNICO_ALERTAS`: correos de alerta. Sin clave no se envían.
- `STORAGE_DIR`: carpeta donde se guardan los documentos (por defecto `uploads`). En Railway, apúntala a un Volume.
- `B2_*`: opcional; si se definen, los documentos van a S3 / Backblaze B2 en lugar del disco.

## Alertas automáticas

`python -m app.alertas_job` revisa vencimientos y plazos de observaciones y envía los correos que
correspondan (una vez por banda de días). Prográmalo una vez al día (cron, Render Cron Job, etc.),
o dispáralo a mano con `POST /admin/enviar-alertas` como admin.

## Despliegue

Build: `pip install -r requirements.txt`. Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
Define como variables de entorno las de `.env.example` que necesites (al menos `DATABASE_URL` y `SECRET_KEY`).

## Endpoints principales

- `GET /config` (público), `POST /auth/login`, `GET /auth/me`
- `GET|POST /empresas`, `GET|PATCH /empresas/{id}`, `GET /empresas/{id}/tramites`
- `GET|POST|PATCH|DELETE /tipos-tramite` (catálogo, solo admin para escribir)
- `POST /tramites`, `PATCH|DELETE /tramites/{id}`, `POST /tramites/importar-csv`
- `POST /tramites/{id}/observaciones`, `PATCH|DELETE /observaciones/{id}`
- `POST /tramites/{id}/documentos`, `DELETE /documentos/{id}`
- `GET /dashboard/proximos-vencer`, `GET /dashboard/resumen`
- `GET|POST|PATCH /usuarios` (solo admin)
