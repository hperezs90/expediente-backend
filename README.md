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

Crea tu primera empresa (esquema propio, administrador y, opcionalmente, un catálogo inicial) y arranca:

```bash
python -m app.tenants crear --subdominio miempresa --nombre "Mi Empresa" \
    --admin-nombre "Ana Pérez" --admin-email ana@miempresa.com --admin-password "una-clave-larga" \
    --catalogo datos/catalogo_ejemplo.csv
export TENANT_POR_DEFECTO=miempresa     # en local, para no depender de subdominios
uvicorn app.main:app --reload
```

Documentación interactiva en http://localhost:8000/docs.

## Multi-empresa (multitenant) y subdominios

Una sola instalación atiende a **varias empresas**, cada una en su subdominio (`acme.miapp.com`,
`beta.miapp.com`). Cada empresa tiene **su propio esquema de PostgreSQL** (`t_acme`, `t_beta`...) con
las mismas tablas: usuarios, empresas, catálogo, trámites y documentos están completamente separados,
y ninguna consulta puede mezclar datos de dos empresas. El esquema `public` solo guarda el registro de
empresas (`tenant`) y el control de migraciones.

- **Detección de la empresa:** encabezado `X-Tenant` (lo manda el frontend según su subdominio), o el subdominio del
  `Host` si defines `BASE_DOMAIN`, o `TENANT_POR_DEFECTO` si no hay ninguno (local o una sola empresa).
- **Seguridad:** el token de sesión lleva la empresa y solo vale en ella; los archivos se guardan en una carpeta por empresa.
- **Marca por empresa:** nombre de la app, eslogan, color, logo y correo de alertas se guardan en el registro de la
  empresa; lo que no se defina usa los valores de la instalación (`APP_NAME`, etc.).
- **Administrar empresas (CLI):**
  ```bash
  python -m app.tenants crear --subdominio acme --nombre "Acme S.A." --admin-nombre ... --admin-email ... --admin-password ...
  python -m app.tenants listar
  python -m app.tenants desactivar --subdominio acme      # (o activar)
  python -m app.tenants migrar                            # aplica migrations/*.sql pendientes a todas las empresas
  python -m app.tenants adoptar --subdominio acme         # convierte una instalación de una sola empresa en una empresa
  ```
- **Administrar empresas (pantalla):** entra a `/plataforma` (por ejemplo `admin.miapp.com/plataforma`, o
  `http://localhost:5173/plataforma` en local) con un **administrador de plataforma**: lista las empresas con sus usuarios y
  trámites, crea empresas nuevas (subdominio, primer administrador con contraseña generada, catálogo de ejemplo y marca),
  edita marca y correo de alertas, activa o desactiva una empresa y restablece la contraseña de cualquier usuario.
  Los administradores de plataforma son independientes de las empresas. El primero se crea con
  `PLATAFORMA_ADMIN_EMAIL` + `PLATAFORMA_ADMIN_PASSWORD` (se aplica al arrancar si todavía no hay ninguno) o con
  `python -m app.tenants crear-superadmin --nombre ... --email ... --password ...` (si el correo ya existe, cambia su contraseña).
- **Administrar empresas (API):** con `PLATAFORMA_TOKEN` definido, `GET|POST /plataforma/empresas`,
  `PATCH /plataforma/empresas/{subdominio}` y `POST /plataforma/empresas/{subdominio}/restablecer-password` aceptan también
  el encabezado `X-Plataforma-Token` (para automatizar). Sin esa variable, ese modo queda deshabilitado; la pantalla usa
  `POST /plataforma/login`.
- **Subdominios en producción:** apunta un DNS comodín `*.miapp.com` al frontend, la API en `api.miapp.com`, y en el
  frontend define `VITE_API_URL=https://api.miapp.com` y `VITE_BASE_DOMAIN=miapp.com`. Para **dar de alta una empresa
  nueva solo hace falta crearla** (CLI o API); no hay que tocar DNS ni desplegar de nuevo.
- Los nombres `www`, `api`, `app`, `admin`, `plataforma`, `mail`, `static` y `public` están reservados.
- Con varios procesos del servidor, activar/desactivar una empresa puede tardar hasta 30 segundos en notarse (caché).

### Catálogo inicial

`datos/catalogo_ejemplo.csv` muestra el formato (`etapas` y `checklist` separados por `|`).
Copia y edítalo con tus propios trámites, o créalos desde la pantalla **Catálogo** del sistema.

### Renovaciones y trámites recurrentes

- **Renovar en un clic:** desde el panel, la ficha de la empresa o el trámite, el botón *Renovar* (visible cuando faltan
  `VENTANA_RENOVACION_DIAS` días o menos, o ya venció) crea el trámite nuevo con la misma empresa, gestor,
  descripción y N° de registro, con checklist en blanco. El trámite anterior queda en "Renovación en curso" y
  enlazado al nuevo. Un trámite se renueva una sola vez, y uno rechazado no se renueva.
- **Recurrentes:** en el catálogo, un tipo marcado *Es recurrente* crea solo el siguiente periodo cuando un trámite
  se marca como aprobado o finalizado: empieza al vencer el actual, o tras `frecuencia_dias` si no tiene vencimiento.

### Documentos y versiones

Se aceptan PDF, JPG y PNG (hasta 15 MB); desde el celular se puede tomar la foto directamente y se
reduce antes de subirla. Cada subida nueva del mismo documento queda como una versión más y las
anteriores se conservan como historial. Los archivos se guardan en `STORAGE_DIR` (o en S3/B2) y se
descargan con enlaces firmados que vencen en una hora. **Respalda esa carpeta junto con la base de datos.**

### Migrar una base del sistema original

Si vienes de la versión anterior (con Ambiente/Alimentos/Farma, "reparos" y campos fijos), ejecuta
**una vez**, en orden, `migrations/001_generico.sql`, `002_version_documentos.sql` y `003_renovaciones.sql` (`psql "$DATABASE_URL" -f ...`), y después `python -m app.tenants adoptar --subdominio <el-subdominio>` para convertirla en una empresa de la plataforma. Conserva los datos: las fechas de
los flujos viejos pasan a las etapas del catálogo y los reparos pasan a observaciones. Haz un respaldo antes.

## Configuración (variables de entorno)

Ver `.env.example`. Lo más relevante:

- `APP_NAME`, `APP_TAGLINE`, `APP_PRIMARY_COLOR`, `APP_LOGO_URL`: identidad visual (el frontend las lee de `GET /config`).
- `VENTANA_RENOVACION_DIAS`: desde cuántos días antes del vencimiento se ofrece "Renovar" (por defecto 90).
- `PLAZO_OBSERVACION_MESES`: plazo para responder una observación (por defecto 3).
- `UMBRALES_VENCIMIENTO` / `UMBRALES_OBSERVACION`: días previos en los que se envían alertas.
- `INACTIVIDAD_MINUTOS`: cierre de sesión automático (0 = desactivado).
- `RESEND_API_KEY`, `ALERT_FROM_EMAIL`, `CORREO_UNICO_ALERTAS`: correos de alerta. Sin clave no se envían.
- `STORAGE_DIR`: carpeta donde se guardan los documentos (por defecto `uploads`). En Railway, apúntala a un Volume.
- `B2_*`: opcional; si se definen, los documentos van a S3 / Backblaze B2 en lugar del disco.

## Alertas automáticas

`python -m app.alertas_job` revisa vencimientos y plazos de observaciones y envía los correos que
correspondan (una vez por banda de días). Recorre todas las empresas activas; prográmalo una vez al día (cron, Railway Cron, etc.),
o dispáralo a mano para una empresa con `POST /admin/enviar-alertas` como admin.

## Despliegue

Build: `pip install -r requirements.txt`. Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
Define como variables de entorno las de `.env.example` que necesites (al menos `DATABASE_URL` y `SECRET_KEY`).

## Endpoints principales

- `GET /config` (público, según la empresa), `GET|POST|PATCH /plataforma/empresas` (token de plataforma), `POST /auth/login`, `GET /auth/me`
- `GET|POST /empresas`, `GET|PATCH /empresas/{id}`, `GET /empresas/{id}/tramites`
- `GET|POST|PATCH|DELETE /tipos-tramite` (catálogo, solo admin para escribir)
- `POST /tramites`, `PATCH|DELETE /tramites/{id}`, `POST /tramites/{id}/renovar`, `POST /tramites/importar-csv`
- `POST /tramites/{id}/observaciones`, `PATCH|DELETE /observaciones/{id}`
- `POST /tramites/{id}/documentos`, `DELETE /documentos/{id}`
- `GET /dashboard/proximos-vencer`, `GET /dashboard/resumen`
- `GET|POST|PATCH /usuarios` (solo admin)
