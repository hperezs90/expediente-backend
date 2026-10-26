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

# Umbrales de alerta por correo, en días antes del vencimiento
UMBRALES_VENCIMIENTO = _lista_enteros("UMBRALES_VENCIMIENTO", "60,30,15")
UMBRALES_OBSERVACION = _lista_enteros("UMBRALES_OBSERVACION", "90,60,30,10")
