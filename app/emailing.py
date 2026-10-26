import os
import re

import requests

from . import config

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_API_URL = os.getenv("RESEND_API_URL", "https://api.resend.com/emails")
# Remitente. Con un dominio verificado en Resend, pon solo la dirección (ej. alertas@miapp.com): el nombre que
# se muestra es el de la empresa (Acme <alertas@miapp.com>). También se acepta el formato completo "Nombre <dirección>".
# Sin dominio verificado se usa onboarding@resend.dev, que solo entrega al correo con el que se registró la cuenta de Resend.
ALERT_FROM_EMAIL = os.getenv("ALERT_FROM_EMAIL", "")


def lista_correos(texto: str | None) -> list:
    """Admite uno o varios correos separados por coma, punto y coma o espacios."""
    return [c for c in re.split(r"[,;\s]+", texto or "") if c]


def remitente(nombre_app: str = "") -> str:
    nombre = (nombre_app or config.APP_NAME).replace('"', "").replace("<", "").replace(">", "")
    if "<" in ALERT_FROM_EMAIL:
        return ALERT_FROM_EMAIL
    return f"{nombre} <{ALERT_FROM_EMAIL or 'onboarding@resend.dev'}>"


def enviar_correo_detallado(destinatarios: list, asunto: str, html: str, nombre_app: str = "") -> tuple:
    """Envía por Resend. Devuelve (ok, error); `error` es un texto legible cuando falla."""
    if not RESEND_API_KEY:
        return False, "RESEND_API_KEY no está configurada en el servidor"
    if not destinatarios:
        return False, "No hay destinatarios (define el correo para alertas de la empresa)"
    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={"from": remitente(nombre_app), "to": destinatarios, "subject": asunto, "html": html},
            timeout=15,
        )
    except requests.RequestException as e:
        return False, f"No se pudo conectar con Resend: {e}"
    if resp.status_code >= 400:
        try:
            detalle = resp.json().get("message") or resp.text
        except ValueError:
            detalle = resp.text
        return False, f"Resend respondió {resp.status_code}: {detalle}"
    return True, ""


def enviar_correo(destinatarios: list, asunto: str, html: str, nombre_app: str = "") -> bool:
    ok, error = enviar_correo_detallado(destinatarios, asunto, html, nombre_app)
    if not ok:
        print(f"Correo no enviado ({asunto}): {error}")
    return ok
