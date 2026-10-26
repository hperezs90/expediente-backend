import hashlib
import hmac
import os
import time
import uuid

# Almacenamiento de documentos. Dos modos, según lo configurado:
#   - S3 / Backblaze B2: si están las variables B2_* (URL firmada de descarga que genera el proveedor).
#   - Disco local: si no, se guarda en STORAGE_DIR (en Railway: un Volume montado, ej. /data/uploads).
#     La descarga usa una URL firmada y con vencimiento que sirve la propia API (GET /archivos/...).
B2_KEY_ID = os.getenv("B2_KEY_ID", "")
B2_APPLICATION_KEY = os.getenv("B2_APPLICATION_KEY", "")
B2_BUCKET_NAME = os.getenv("B2_BUCKET_NAME", "")
B2_ENDPOINT_URL = os.getenv("B2_ENDPOINT_URL", "")  # ej. https://s3.us-west-004.backblazeb2.com

STORAGE_DIR = os.path.abspath(os.getenv("STORAGE_DIR", "uploads"))

EXTENSIONES_PERMITIDAS = {".pdf", ".jpg", ".jpeg", ".png"}
TAMANO_MAXIMO_BYTES = 15 * 1024 * 1024  # 15 MB

# Primeros bytes de cada formato, para no aceptar un archivo con una extensión que no le corresponde
FIRMAS = {
    ".pdf": (b"%PDF",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
}
TIPOS_MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def usa_s3() -> bool:
    return bool(B2_KEY_ID and B2_APPLICATION_KEY and B2_ENDPOINT_URL and B2_BUCKET_NAME)


def _cliente():
    import boto3
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=B2_ENDPOINT_URL,
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APPLICATION_KEY,
        config=Config(signature_version="s3v4"),
    )


def validar_archivo(nombre_archivo: str, tamano_bytes: int, contenido: bytes = b"") -> str | None:
    ext = os.path.splitext(nombre_archivo)[1].lower()
    if ext not in EXTENSIONES_PERMITIDAS:
        return f"Tipo de archivo no permitido ({ext}). Solo PDF, JPG o PNG."
    if tamano_bytes > TAMANO_MAXIMO_BYTES:
        return "El archivo pesa más de 15 MB."
    if contenido and not contenido.startswith(FIRMAS[ext]):
        return "El contenido del archivo no corresponde a su extensión."
    return None


def _ruta_local(clave: str) -> str:
    """Resuelve la clave dentro de STORAGE_DIR; rechaza cualquier intento de salirse de la carpeta."""
    ruta = os.path.abspath(os.path.join(STORAGE_DIR, clave))
    if os.path.commonpath([ruta, STORAGE_DIR]) != STORAGE_DIR:
        raise ValueError("Clave de archivo inválida")
    return ruta


def subir_archivo(contenido: bytes, nombre_original: str, content_type: str, prefijo: str = "") -> str:
    """Guarda el archivo y devuelve la clave (key) con la que quedó guardado.
    `prefijo` separa los archivos de cada empresa (subdominio) en carpetas distintas."""
    ext = os.path.splitext(nombre_original)[1].lower()
    clave = f"documentos/{prefijo}/{uuid.uuid4()}{ext}" if prefijo else f"documentos/{uuid.uuid4()}{ext}"
    if usa_s3():
        _cliente().put_object(
            Bucket=B2_BUCKET_NAME,
            Key=clave,
            Body=contenido,
            ContentType=content_type or "application/octet-stream",
        )
    else:
        ruta = _ruta_local(clave)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            f.write(contenido)
    return clave


def _firma(clave: str, expira: int) -> str:
    secreto = os.getenv("SECRET_KEY", "cambia-esto-en-produccion").encode()
    return hmac.new(secreto, f"{clave}|{expira}".encode(), hashlib.sha256).hexdigest()


def firma_valida(clave: str, expira: int, firma: str) -> bool:
    return expira >= time.time() and hmac.compare_digest(_firma(clave, expira), firma)


def generar_url_descarga(clave: str, expira_segundos: int = 3600) -> str:
    """URL temporal (1 hora por defecto) para descargar el archivo, sin hacerlo público.
    En modo local es una ruta relativa de esta misma API; el frontend le antepone la URL del backend."""
    if usa_s3():
        return _cliente().generate_presigned_url(
            "get_object",
            Params={"Bucket": B2_BUCKET_NAME, "Key": clave},
            ExpiresIn=expira_segundos,
        )
    expira = int(time.time()) + expira_segundos
    return f"/archivos/{clave}?exp={expira}&sig={_firma(clave, expira)}"


def leer_ruta_local(clave: str) -> str | None:
    """Ruta del archivo en disco, o None si no existe."""
    ruta = _ruta_local(clave)
    return ruta if os.path.isfile(ruta) else None


def borrar_archivo(clave: str):
    if usa_s3():
        _cliente().delete_object(Bucket=B2_BUCKET_NAME, Key=clave)
        return
    ruta = _ruta_local(clave)
    if os.path.isfile(ruta):
        os.remove(ruta)
