"""CLI minima para crear clientes API y usuarios (no hay endpoint publico para esto:
es un paso administrativo, igual que crear una API key en cualquier proveedor).

Uso:
    python scripts/admin_cli.py crear-cliente "Portal Abogados"
        -> imprime el x-client-key en texto plano UNA sola vez.

    python scripts/admin_cli.py crear-usuario <cliente_id> usuario@correo.cl "password"
"""

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.auth.security import hash_password, hash_secreto
from api.db.models.auth import ClienteApi, Usuario
from api.db.session_sync import session_scope


def crear_cliente(nombre: str) -> None:
    client_key = f"cka_{secrets.token_urlsafe(24)}"
    with session_scope() as session:
        cliente = ClienteApi(nombre=nombre, client_key_hash=hash_secreto(client_key), activo=True)
        session.add(cliente)
        session.flush()
        print(f"Cliente creado: id={cliente.id} nombre={cliente.nombre}")
        print(f"x-client-key (guardala ahora, no se vuelve a mostrar): {client_key}")


def crear_usuario(cliente_id: str, email: str, password: str) -> None:
    with session_scope() as session:
        usuario = Usuario(
            cliente_id=cliente_id, email=email, password_hash=hash_password(password), activo=True
        )
        session.add(usuario)
        session.flush()
        print(f"Usuario creado: id={usuario.id} email={usuario.email} cliente_id={usuario.cliente_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)

    p_cliente = sub.add_parser("crear-cliente")
    p_cliente.add_argument("nombre")

    p_usuario = sub.add_parser("crear-usuario")
    p_usuario.add_argument("cliente_id")
    p_usuario.add_argument("email")
    p_usuario.add_argument("password")

    args = parser.parse_args()

    if args.comando == "crear-cliente":
        crear_cliente(args.nombre)
    elif args.comando == "crear-usuario":
        crear_usuario(args.cliente_id, args.email, args.password)


if __name__ == "__main__":
    main()
