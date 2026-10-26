from fastapi import Request
from slowapi import Limiter


def obtener_ip_real(request: Request) -> str:
    """Render/Cloudflare/Railway pasan la IP real del visitante en X-Forwarded-For."""
    reenviada = request.headers.get("x-forwarded-for")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.client.host if request.client else "desconocido"


limiter = Limiter(key_func=obtener_ip_real, default_limits=["100/minute"])
