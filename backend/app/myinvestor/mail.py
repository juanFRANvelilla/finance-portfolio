"""Lectura de correos Gmail vía IMAP SSL (solo lectura)."""

from __future__ import annotations

import email
import html
import imaplib
import re
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import Message

FALLBACK_CHARSETS = ("utf-8", "iso-8859-1", "latin-1", "windows-1252")


@dataclass(frozen=True)
class MailMessage:
    uid: str
    message_id: str | None
    subject: str
    sender: str
    date: str | None
    body: str


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
    candidates.extend(item for item in FALLBACK_CHARSETS if item not in candidates)
    for encoding in candidates:
        try:
            return payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def html_to_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h\d)\s*>", "\n", text)
    text = re.sub(r"(?i)</t[dh]\s*>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
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


def fetch_mailbox_messages(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    mailbox: str,
    limit: int | None = None,
) -> list[MailMessage]:
    """Descarga los correos de una etiqueta/carpeta IMAP sin modificar flags."""
    conn = imaplib.IMAP4_SSL(host, port, timeout=30)
    try:
        conn.login(user, password)
        target = quote_mailbox(mailbox)
        status, data = conn.select(target, readonly=True)
        if status != "OK":
            raise RuntimeError(f"No se pudo abrir {target}: {status} {data!r}")

        status, data = conn.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []

        uids = data[0].decode().split()
        if limit is not None:
            uids = uids[:limit]

        messages: list[MailMessage] = []
        for uid in uids:
            status, fetched = conn.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                continue
            raw = fetched[0][1]
            if not isinstance(raw, (bytes, bytearray)):
                continue
            msg = email.message_from_bytes(raw)
            messages.append(
                MailMessage(
                    uid=uid,
                    message_id=msg.get("Message-ID"),
                    subject=decode_mime_header(msg.get("Subject")),
                    sender=decode_mime_header(msg.get("From")),
                    date=msg.get("Date"),
                    body=extract_body(msg),
                )
            )
        return messages
    finally:
        try:
            conn.close()
        except imaplib.IMAP4.error:
            pass
        conn.logout()
