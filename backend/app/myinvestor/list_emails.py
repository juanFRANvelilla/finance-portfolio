"""
Lista correos de una etiqueta Gmail vía IMAP SSL (solo lectura, sin BD).

Uso:
    cd backend/
    source .venv/bin/activate
    python -m app.myinvestor.list_emails
    python -m app.myinvestor.list_emails --limit 3

Requiere en .env:
    IMAP_USER, IMAP_PASSWORD
    IMAP_HOST (opcional, default imap.gmail.com)
    IMAP_PORT (opcional, default 993)
    IMAP_MAILBOX (opcional, default MyInvestor/Movimientos)
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from textwrap import indent

from dotenv import load_dotenv

from app.myinvestor.mail import fetch_mailbox_messages

BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=BACKEND_ROOT / ".env")


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or not str(value).strip():
        raise SystemExit(f"Falta variable de entorno {name} en backend/.env")
    return str(value).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Listar correos Gmail por etiqueta (IMAP)")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de correos a mostrar")
    args = parser.parse_args()

    host = env("IMAP_HOST", "imap.gmail.com")
    port = int(env("IMAP_PORT", "993"))
    user = env("IMAP_USER")
    password = env("IMAP_PASSWORD")
    mailbox = env("IMAP_MAILBOX", "MyInvestor/Movimientos")

    print(f"Conectando a {host}:{port} como {user} …")
    messages = fetch_mailbox_messages(
        host=host,
        port=port,
        user=user,
        password=password,
        mailbox=mailbox,
        limit=args.limit,
    )
    if not messages:
        print(f"No hay correos en {mailbox!r}")
        return

    print(f"Encontrados {len(messages)} correo(s) en {mailbox!r}\n")
    total = len(messages)
    for index, message in enumerate(messages, start=1):
        print("=" * 72)
        print(f"[{index}/{total}] UID={message.uid}")
        print("-" * 72)
        print(f"Message-ID : {message.message_id or '(n/a)'}")
        print(f"Asunto     : {message.subject}")
        print(f"Remitente  : {message.sender}")
        print(f"Fecha      : {message.date or '(n/a)'}")
        print("-" * 72)
        print("CUERPO:")
        print(indent(message.body or "(vacío)", "  "))
        print("=" * 72)
        print()


if __name__ == "__main__":
    main()
