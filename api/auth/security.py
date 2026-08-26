import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

TOKEN_TTL = timedelta(hours=12)


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verificar_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def hash_secreto(valor: str) -> str:
    """SHA-256 usado tanto para client keys como para bearer tokens: son secretos
    aleatorios de alta entropia (no passwords de humano), asi que un hash rapido e
    indexable es apropiado -- lo importante es no guardar el valor en texto plano."""
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def generar_token() -> str:
    return secrets.token_urlsafe(32)


def expiracion_token(ahora: datetime | None = None) -> datetime:
    ahora = ahora or datetime.now(timezone.utc)
    return ahora + TOKEN_TTL
