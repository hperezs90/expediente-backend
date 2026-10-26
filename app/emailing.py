import os
import requests

from . import config

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
# Mientras la cuenta de Resend no tenga un dominio verificado, solo puede mandar
# correos a la misma dirección con la que se registró la cuenta.
ALERT_FROM_EMAIL = os.getenv("ALERT_FROM_EMAIL", "")


def enviar_correo(destinatarios: list, asunto: str, html: str, nombre_app: str = "") -> bool:
    if not RESEND_API_KEY:
        print("RESEND_API_KEY no configurada; correo no enviado:", asunto)
        return False
    if not destinatarios:
        return False

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={
                "from": ALERT_FROM_EMAIL or f"{nombre_app or config.APP_NAME} <onboarding@resend.dev>",
                "to": destinatarios,
                "subject": asunto,
                "html": html,
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            print("Error de Resend:", resp.status_code, resp.text)
            return False
        return True
    except requests.RequestException as e:
        print("Error de red al enviar correo:", e)
        return False
