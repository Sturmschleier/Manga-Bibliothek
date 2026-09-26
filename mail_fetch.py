"""
mail_fetch.py
Ruft Bestellbestätigungen direkt aus einem E-Mail-Postfach ab - per IMAP und
damit anbieterunabhängig (GMX, WEB.DE, Gmail, eigener Server, ...).

Sicherheits-/Datenschutz-Grundsätze:
  - Der Ordner wird schreibgeschützt geöffnet und die Mails werden mit
    BODY.PEEK geladen: im Postfach wird nichts verändert (auch nicht das
    "gelesen"-Kennzeichen), nichts gelöscht.
  - Die Mails werden nur im Speicher ausgewertet (order_mail.py), nichts
    davon wird abgelegt.
  - Das Passwort steht nie in config.json: entweder in den Windows-Anmelde-
    informationen (Paket "keyring", optional) oder es wird bei Bedarf
    abgefragt und nur im Arbeitsspeicher gehalten.
  - Verschlüsselte Verbindung (SSL/TLS oder STARTTLS) mit Zertifikatsprüfung.

Hinweis: Anbieter, die für IMAP nur OAuth2 zulassen (z.B. Outlook.com),
funktionieren mit Benutzername/Passwort nicht. Bei Gmail, GMX, WEB.DE u.ä.
ist meist ein separates "App-Passwort" bzw. die Freigabe des IMAP-Zugriffs in
den Kontoeinstellungen nötig.
"""

import imaplib
import re
import socket
import ssl
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

import config
import order_mail

KEYRING_SERVICE = "MangaLibrary-IMAP"
TIMEOUT_SECONDS = 30
MAX_HEADER_CANDIDATES = 100  # so viele (neueste) Treffer der Server-Suche werden anhand ihrer Kopfzeilen geprüft

# Komfort-Voreinstellungen (füllen nur Server/Port/Verschlüsselung aus -
# jeder andere IMAP-Server lässt sich frei eintragen).
PRESETS = {
    "GMX": ("imap.gmx.net", 993, "ssl"),
    "WEB.DE": ("imap.web.de", 993, "ssl"),
    "Gmail (App-Passwort)": ("imap.gmail.com", 993, "ssl"),
    "Yahoo": ("imap.mail.yahoo.com", 993, "ssl"),
    "iCloud (App-Passwort)": ("imap.mail.me.com", 993, "ssl"),
    "T-Online": ("secureimap.t-online.de", 993, "ssl"),
    "IONOS": ("imap.ionos.de", 993, "ssl"),
    "Posteo": ("posteo.de", 993, "ssl"),
    "mailbox.org": ("imap.mailbox.org", 993, "ssl"),
}

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class MailError(Exception):
    """Fehler beim Postfach-Zugriff, Text ist für den Nutzer gedacht."""


@dataclass
class MailSettings:
    host: str = ""
    port: int = 993
    security: str = "ssl"          # "ssl" oder "starttls"
    user: str = ""
    folder: str = "INBOX"
    sender: str = "konold"         # Absender enthält (leer = egal)
    subject: str = "Bestellung"    # Betreff enthält (leer = egal)
    days_back: int = 90
    max_messages: int = 30

    @property
    def configured(self) -> bool:
        return bool(self.host.strip() and self.user.strip())

    @property
    def credential_key(self) -> str:
        return f"{self.user}@{self.host}"


@dataclass
class FetchedMail:
    uid: str
    sender: str = ""
    subject: str = ""
    date: Optional[datetime] = None
    items: list = field(default_factory=list)   # order_mail.OrderItem
    error: Optional[str] = None                 # z.B. "keine Artikelliste" (Versandmail o.ä.)


# --------------------------------------------------------------- Einstellungen

def load_settings() -> MailSettings:
    security = str(config.get("mail_imap_security", "ssl")).lower()
    return MailSettings(
        host=str(config.get("mail_imap_host", "") or "").strip(),
        port=config.get_int("mail_imap_port", 993),
        security=security if security in ("ssl", "starttls") else "ssl",
        user=str(config.get("mail_imap_user", "") or "").strip(),
        folder=str(config.get("mail_folder", "INBOX") or "INBOX").strip(),
        sender=str(config.get("mail_filter_sender", "") or "").strip(),
        subject=str(config.get("mail_filter_subject", "") or "").strip(),
        days_back=max(1, config.get_int("mail_days_back", 90)),
        max_messages=max(1, config.get_int("mail_max_messages", 30)),
    )


def save_settings(s: MailSettings) -> None:
    cfg = config.load()
    cfg.update({
        "mail_imap_host": s.host.strip(),
        "mail_imap_port": int(s.port),
        "mail_imap_security": s.security,
        "mail_imap_user": s.user.strip(),
        "mail_folder": s.folder.strip() or "INBOX",
        "mail_filter_sender": s.sender.strip(),
        "mail_filter_subject": s.subject.strip(),
        "mail_days_back": int(s.days_back),
        "mail_max_messages": int(s.max_messages),
    })
    config.save(cfg)


# ------------------------------------------------------------------ Passwort

def _keyring():
    """Liefert das Keyring-Backend oder None, wenn nicht verfügbar. Unter
    Windows wird der Tresor der Windows-Anmeldeinformationen direkt
    verwendet (kein Plugin-Suchlauf nötig - funktioniert so auch in der
    gebündelten exe)."""
    try:
        if sys.platform == "win32":
            from keyring.backends.Windows import WinVaultKeyring
            return WinVaultKeyring()
        import keyring
        return keyring.get_keyring()
    except Exception:  # noqa: BLE001 - fehlendes Paket/Backend = einfach "nicht verfügbar"
        return None


def keyring_available() -> bool:
    return _keyring() is not None


def get_saved_password(settings: MailSettings) -> Optional[str]:
    backend = _keyring()
    if backend is None or not settings.user:
        return None
    try:
        return backend.get_password(KEYRING_SERVICE, settings.credential_key)
    except Exception:  # noqa: BLE001
        return None


def save_password(settings: MailSettings, password: str) -> bool:
    backend = _keyring()
    if backend is None:
        return False
    try:
        backend.set_password(KEYRING_SERVICE, settings.credential_key, password)
        return True
    except Exception:  # noqa: BLE001
        return False


def delete_saved_password(settings: MailSettings) -> None:
    backend = _keyring()
    if backend is None:
        return
    try:
        backend.delete_password(KEYRING_SERVICE, settings.credential_key)
    except Exception:  # noqa: BLE001 - nichts gespeichert = nichts zu löschen
        pass


# ------------------------------------------------------------------ Verbindung

def _connect(settings: MailSettings):
    context = ssl.create_default_context()
    if settings.security == "starttls":
        conn = imaplib.IMAP4(settings.host, settings.port, timeout=TIMEOUT_SECONDS)
        conn.starttls(ssl_context=context)
        return conn
    return imaplib.IMAP4_SSL(settings.host, settings.port, ssl_context=context, timeout=TIMEOUT_SECONDS)


def _open(settings: MailSettings, password: str, connect: Optional[Callable] = None):
    """Verbindet, meldet an und öffnet den Ordner SCHREIBGESCHÜTZT. Gibt
    (Verbindung, Anzahl Nachrichten im Ordner) zurück."""
    if not settings.configured:
        raise MailError("Server und Benutzername sind noch nicht eingetragen.")
    try:
        conn = (connect or _connect)(settings)
    except ssl.SSLError as exc:
        raise MailError(f"Sichere Verbindung fehlgeschlagen ({exc}). Port/Verschlüsselung prüfen.") from exc
    except (OSError, socket.timeout, imaplib.IMAP4.error) as exc:
        raise MailError(f"Keine Verbindung zu {settings.host}:{settings.port} möglich ({exc}).") from exc

    try:
        try:
            conn.login(settings.user, password)
        except imaplib.IMAP4.error as exc:
            raise MailError(
                "Anmeldung fehlgeschlagen. Benutzername/Passwort prüfen - bei manchen Anbietern ist ein "
                "App-Passwort bzw. die Freigabe des IMAP-Zugriffs in den Kontoeinstellungen nötig."
                f"\n\nAntwort des Servers: {_text(exc)}"
            ) from exc
        folder = settings.folder or "INBOX"
        quoted = f'"{folder}"' if re.search(r'[\s"]', folder) and not folder.startswith('"') else folder
        typ, data = conn.select(quoted, readonly=True)
        if typ != "OK":
            raise MailError(f"Der Ordner „{folder}“ konnte nicht geöffnet werden ({_text(data)}).")
        try:
            count = int(data[0])
        except (TypeError, ValueError, IndexError):
            count = 0
        return conn, count
    except BaseException:
        _close(conn)
        raise


def _close(conn) -> None:
    try:
        conn.logout()
    except Exception:  # noqa: BLE001 - beim Aufräumen egal
        pass


def _text(value) -> str:
    if isinstance(value, (list, tuple)):
        value = b" ".join(v if isinstance(v, bytes) else str(v).encode() for v in value)
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return str(value).strip()


def test_connection(settings: MailSettings, password: str, connect: Optional[Callable] = None) -> int:
    """Prüft Server, Anmeldung und Ordner. Gibt die Anzahl Nachrichten im
    Ordner zurück; löst MailError aus, wenn etwas nicht funktioniert."""
    conn, count = _open(settings, password, connect)
    _close(conn)
    return count


# ------------------------------------------------------------------ Abruf

def _imap_date(d: date) -> str:
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"  # unabhängig von der Systemsprache


def _decode_header_value(value) -> str:
    try:
        return str(make_header(decode_header(str(value or "")))).strip()
    except Exception:  # noqa: BLE001 - kaputte Kopfzeile: Rohtext verwenden
        return str(value or "").strip()


def _fetch_bytes(conn, uid: str, part: str) -> bytes:
    typ, data = conn.uid("FETCH", uid, f"(BODY.PEEK[{part}])")
    if typ != "OK":
        raise MailError(f"Nachricht {uid} konnte nicht geladen werden ({_text(data)}).")
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    raise MailError(f"Nachricht {uid} war leer.")


def fetch_orders(settings: MailSettings, password: str, connect: Optional[Callable] = None,
                 today: Optional[date] = None) -> list[FetchedMail]:
    """
    Sucht im Ordner nach Mails der letzten `days_back` Tage (Absender-Filter
    serverseitig, Betreff/Absender zusätzlich lokal), lädt die neuesten
    `max_messages` Treffer und liest die Artikelliste aus.

    Gibt eine Liste von FetchedMail zurück, neueste zuerst. Mails ohne
    auswertbare Artikelliste (z.B. Versandbenachrichtigungen) haben `error`
    gesetzt und `items` leer.
    """
    today = today or date.today()
    conn, _count = _open(settings, password, connect)
    try:
        criteria = ["SINCE", _imap_date(today - timedelta(days=settings.days_back))]
        sender = settings.sender.strip()
        if sender and sender.isascii() and '"' not in sender:
            criteria += ["FROM", f'"{sender}"']
        typ, data = conn.uid("SEARCH", *criteria)
        if typ != "OK":
            raise MailError(f"Suche im Postfach fehlgeschlagen ({_text(data)}).")
        uids = (data[0] or b"").decode().split() if data else []
        uids = uids[-MAX_HEADER_CANDIDATES:]

        sender_f = sender.casefold()
        subject_f = settings.subject.strip().casefold()
        candidates = []
        for uid in reversed(uids):  # neueste zuerst
            try:
                raw_headers = _fetch_bytes(conn, uid, "HEADER.FIELDS (FROM SUBJECT DATE)")
            except MailError:
                continue  # einzelne nicht ladbare Nachricht überspringen statt den ganzen Abruf abzubrechen
            headers = BytesParser(policy=policy.default).parsebytes(raw_headers, headersonly=True)
            from_h = _decode_header_value(headers["From"])
            subj_h = _decode_header_value(headers["Subject"])
            if sender_f and sender_f not in from_h.casefold():
                continue
            if subject_f and subject_f not in subj_h.casefold():
                continue
            try:
                sent = parsedate_to_datetime(str(headers["Date"]))
            except (TypeError, ValueError):
                sent = None
            candidates.append(FetchedMail(uid=uid, sender=from_h, subject=subj_h, date=sent))
            if len(candidates) >= settings.max_messages:
                break

        # Jede Mail für sich: eine nicht ladbare oder nicht lesbare Mail wird
        # nur markiert (mail.error), die übrigen werden trotzdem ausgewertet.
        for mail in candidates:
            try:
                mail.items = order_mail.parse_message_bytes(_fetch_bytes(conn, mail.uid, ""))
            except (MailError, ValueError) as exc:
                mail.error = str(exc)
        return candidates
    except (OSError, socket.timeout, imaplib.IMAP4.error) as exc:
        raise MailError(f"Fehler beim Abruf aus dem Postfach: {exc}") from exc
    finally:
        _close(conn)
