"""
Lista correos de una etiqueta Gmail vía IMAP SSL (solo lectura, sin BD).

Uso:
    cd backend/
    source .venv/bin/activate
    python -m app.myinvestor.list_emails
    python -m app.myinvestor.list_emails --limit 3

Requiere en .env:
    IMAP_HOST, IMAP_USER, IMAP_PASSWORD, IMAP_MAILBOX
    IMAP_PORT (opcional, default 993)
"""

from __future__ import annotations

import argparse
import email
import html
import imaplib
import os
import re
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path
from textwrap import indent

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=BACKEND_ROOT / ".env")

FALLBACK_CHARSETS = ("utf-8", "iso-8859-1", "latin-1", "windows-1252")


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or not str(value).strip():
        raise SystemExit(f"Falta variable de entorno {name} en backend/.env")
    return str(value).strip()


def quote_mailbox(mailbox: str) -> str:
    return f'"{mailbox.strip().strip(chr(34))}"'


def decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        parts: list[str] = []
        for fragment, charset in decode_header(value):
            if isinstance(fragment, bytes):
                parts.append(decode_bytes(fragment, charset))
            else:
                parts.append(fragment)
        return "".join(parts)


def decode_bytes(payload: bytes, charset: str | None = None) -> str:
    candidates = []
    if charset:
        candidates.append(charset.strip().lower())
    candidates.extend(c for c in FALLBACK_CHARSETS if c not in candidates)
    for encoding in candidates:
        try:
            return payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def html_to_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li)\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def part_charset(part: Message) -> str | None:
    return part.get_content_charset()


def decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        return decode_bytes(payload, part_charset(part))
    if isinstance(payload, str):
        return payload
    raw = part.get_payload(decode=False)
    if isinstance(raw, str):
        return raw
    return ""


def extract_body(msg: Message) -> str:
    plain: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = str(part.get("Content-Disposition", "")).lower()
            if "attachment" in disp:
                continue
            if ctype == "text/plain":
                plain.append(decode_part(part))
            elif ctype == "text/html":
                html_parts.append(decode_part(part))
    else:
        ctype = (msg.get_content_type() or "").lower()
        text = decode_part(msg)
        return html_to_text(text) if ctype == "text/html" else text.strip()

    if plain:
        return plain[0].strip()
    if html_parts:
        return html_to_text(html_parts[0])
    return ""


def print_email(uid: str, msg: Message, index: int, total: int) -> None:
    body = extract_body(msg)
    print("=" * 72)
    print(f"[{index}/{total}] UID={uid}")
    print("-" * 72)
    print(f"Message-ID : {msg.get('Message-ID') or '(n/a)'}")
    print(f"Asunto     : {decode_mime_header(msg.get('Subject'))}")
    print(f"Remitente  : {decode_mime_header(msg.get('From'))}")
    print(f"Fecha      : {msg.get('Date') or '(n/a)'}")
    print("-" * 72)
    print("CUERPO:")
    print(indent(body or "(vacío)", "  "))
    print("=" * 72)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Listar correos Gmail por etiqueta (IMAP)")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de correos a mostrar")
    args = parser.parse_args()

    host = env("IMAP_HOST", "imap.gmail.com")
    port = int(env("IMAP_PORT", "993"))
    user = env("IMAP_USER")
    password = env("IMAP_PASSWORD")
    mailbox = env("IMAP_MAILBOX")

    print(f"Conectando a {host}:{port} como {user} …")
    conn = imaplib.IMAP4_SSL(host, port)
    try:
        conn.login(user, password)
        target = quote_mailbox(mailbox)
        status, data = conn.select(target, readonly=True)
        if status != "OK":
            raise SystemExit(f"No se pudo abrir {target}: {status} {data!r}")

        status, data = conn.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            print(f"No hay correos en {mailbox!r}")
            return

        uids = data[0].decode().split()
        if args.limit is not None:
            uids = uids[: args.limit]

        print(f"Encontrados {len(uids)} correo(s) en {mailbox!r}\n")
        for i, uid in enumerate(uids, start=1):
            status, fetched = conn.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                print(f"Error fetch UID={uid}")
                continue
            raw = fetched[0][1]
            msg = email.message_from_bytes(raw)
            print_email(uid, msg, i, len(uids))
    finally:
        try:
            conn.close()
        except imaplib.IMAP4.error:
            pass
        conn.logout()


if __name__ == "__main__":
    main()
