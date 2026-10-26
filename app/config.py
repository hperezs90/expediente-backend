import os


def _lista_enteros(nombre: str, por_defecto: str) -> list:
    crudo = os.getenv(nombre, por_defecto)
    return sorted({int(x) for x in crudo.split(",") if x.strip()}, reverse=True)


# Identidad de la instalación (cada empresa configura la suya con variables de entorno)
APP_NAME = os.getenv("APP_NAME", "Expediente")
APP_TAGLINE = os.getenv("APP_TAGLINE", "Ningún trámite se vence sin avisar.")
APP_PRIMARY_COLOR = os.getenv("APP_PRIMARY_COLOR", "#2e7d4f")
APP_LOGO_URL = os.getenv("APP_LOGO_URL", "")

# Cierre de sesión automático por inactividad (0 = desactivado)
INACTIVIDAD_MINUTOS = int(os.getenv("INACTIVIDAD_MINUTOS", "5"))

# Plazo estándar (en meses calendario) para responder una observación de la entidad
PLAZO_OBSERVACION_MESES = int(os.getenv("PLAZO_OBSERVACION_MESES", "3"))

# Desde cuántos días antes del vencimiento se ofrece "Renovar" en el panel
VENTANA_RENOVACION_DIAS = int(os.getenv("VENTANA_RENOVACION_DIAS", "90"))

# Umbrales de alerta por correo, en días antes del vencimiento
UMBRALES_VENCIMIENTO = _lista_enteros("UMBRALES_VENCIMIENTO", "60,30,15")
UMBRALES_OBSERVACION = _lista_enteros("UMBRALES_OBSERVACION", "90,60,30,10")

# --- Multi-empresa (multitenant): una empresa por subdominio, cada una en su propio esquema de PostgreSQL ---
# Dominio base: "miapp.com" hace que acme.miapp.com sea la empresa "acme" (se detecta por el Host de la petición).
# Cuando el frontend vive en otro dominio que la API, el frontend manda la empresa en el encabezado X-Tenant.
BASE_DOMAIN = os.getenv("BASE_DOMAIN", "").lower().lstrip(".")
# Empresa a usar cuando la petición no indica ninguna (desarrollo local o instalación de una sola empresa)
TENANT_POR_DEFECTO = os.getenv("TENANT_POR_DEFECTO", "").lower()
SUBDOMINIOS_RESERVADOS = {"www", "api", "app", "admin", "plataforma", "mail", "static", "public", "localhost"}
# Token para el API de administración de la plataforma (crear/listar empresas). Sin valor, ese API queda deshabilitado.
PLATAFORMA_TOKEN = os.getenv("PLATAFORMA_TOKEN", "")
# Primer administrador de la plataforma (pantalla /plataforma). Se crea al arrancar si todavía no hay ninguno.
PLATAFORMA_ADMIN_EMAIL = os.getenv("PLATAFORMA_ADMIN_EMAIL", "")
PLATAFORMA_ADMIN_PASSWORD = os.getenv("PLATAFORMA_ADMIN_PASSWORD", "")
