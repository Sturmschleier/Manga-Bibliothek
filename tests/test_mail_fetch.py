"""
tests/test_mail_fetch.py
Tests für mail_fetch.py mit einem Fake-IMAP-Server (kein Netzwerk, keine
echten Zugangsdaten).
"""

import imaplib
from datetime import date
from email.message import EmailMessage

import pytest

import mail_fetch

HTML = (
    "<html><body><table>"
    "<tr><td>Sanda - Band 12</td><td>1</td><td>9,00 EUR</td></tr>"
    "<tr><td>Fabiniku 14</td><td>1</td><td>9,00 EUR</td></tr>"
    "</table></body></html>"
)


def _mail(subject, sender="Buchhandlung Konold <service@buchhandlung.de>", html=HTML):
    msg = EmailMessage()
    msg["From"] = sender
    msg["Subject"] = subject
    msg["Date"] = "Sat, 29 Aug 2026 08:09:55 +0200"
    msg.set_content("Text", subtype="plain")
    msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


class FakeIMAP:
    def __init__(self, messages, login_ok=True, folder_ok=True):
        self.messages = messages          # {uid(str): rawbytes}
        self.login_ok = login_ok
        self.folder_ok = folder_ok
        self.selected = None
        self.readonly = None
        self.commands = []
        self.logged_out = False

    def login(self, user, password):
        if not self.login_ok:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")

    def select(self, folder, readonly=False):
        self.selected, self.readonly = folder, readonly
        if not self.folder_ok:
            return "NO", [b"no such folder"]
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, command, *args):
        self.commands.append((command, args))
        if command == "SEARCH":
            return "OK", [" ".join(self.messages).encode()]
        uid, spec = args
        raw = self.messages[uid]
        if "HEADER.FIELDS" in spec:
            raw = raw.split(b"\n\n", 1)[0] + b"\n\n" if b"\n\n" in raw else raw
        return "OK", [(f"1 (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw), b")"]

    def logout(self):
        self.logged_out = True


def _settings(**kw):
    base = {"host": "imap.example.org", "user": "me@example.org", "sender": "konold", "subject": "Bestellung"}
    base.update(kw)
    return mail_fetch.MailSettings(**base)


def test_fetch_returns_matching_orders_newest_first_and_never_writes():
    server = FakeIMAP({
        "1": _mail("Vielen Dank für Ihre Bestellung"),
        "2": _mail("Newsletter August"),
        "3": _mail("Ihre Bestellung", sender="Anderer Shop <x@example.com>"),
        "4": _mail("Vielen Dank für Ihre Bestellung"),
    })
    mails = mail_fetch.fetch_orders(_settings(), "pw", connect=lambda s: server, today=date(2026, 9, 1))

    assert [m.uid for m in mails] == ["4", "1"]          # Newsletter & fremder Absender gefiltert, neueste zuerst
    assert [i.name for i in mails[0].items] == ["Sanda - Band 12", "Fabiniku 14"]
    assert mails[0].error is None
    assert server.readonly is True                         # Ordner schreibgeschützt geöffnet
    assert server.logged_out
    fetches = [a[1] for c, a in server.commands if c == "FETCH"]
    assert all(spec.startswith("(BODY.PEEK[") for spec in fetches)   # PEEK: "gelesen"-Status bleibt unverändert


def test_search_uses_ascii_date_and_sender_filter():
    server = FakeIMAP({"1": _mail("Bestellung")})
    mail_fetch.fetch_orders(_settings(days_back=30), "pw", connect=lambda s: server, today=date(2026, 9, 1))
    search = next(a for c, a in server.commands if c == "SEARCH")
    assert search == ("SINCE", "02-Aug-2026", "FROM", '"konold"')


def test_mail_without_article_list_is_reported_with_error():
    shipping_note = "<html><body><p>Ihr Paket ist unterwegs</p></body></html>"
    server = FakeIMAP({"1": _mail("Bestellung versendet", html=shipping_note)})
    mails = mail_fetch.fetch_orders(_settings(), "pw", connect=lambda s: server)
    assert len(mails) == 1 and mails[0].items == [] and mails[0].error


def test_max_messages_limit():
    server = FakeIMAP({str(i): _mail("Bestellung") for i in range(1, 8)})
    mails = mail_fetch.fetch_orders(_settings(max_messages=3), "pw", connect=lambda s: server)
    assert [m.uid for m in mails] == ["7", "6", "5"]


def test_login_failure_gives_clear_error_and_closes_connection():
    server = FakeIMAP({}, login_ok=False)
    with pytest.raises(mail_fetch.MailError, match="Anmeldung fehlgeschlagen"):
        mail_fetch.fetch_orders(_settings(), "falsch", connect=lambda s: server)
    assert server.logged_out


def test_unknown_folder_is_reported():
    server = FakeIMAP({}, folder_ok=False)
    with pytest.raises(mail_fetch.MailError, match="Ordner"):
        mail_fetch.test_connection(_settings(folder="Nope"), "pw", connect=lambda s: server)


def test_folder_with_space_is_quoted():
    server = FakeIMAP({})
    mail_fetch.test_connection(_settings(folder="Meine Bestellungen"), "pw", connect=lambda s: server)
    assert server.selected == '"Meine Bestellungen"'


def test_unconfigured_settings_raise():
    with pytest.raises(mail_fetch.MailError):
        mail_fetch.test_connection(mail_fetch.MailSettings(), "pw", connect=lambda s: FakeIMAP({}))


def test_test_connection_returns_message_count():
    assert mail_fetch.test_connection(_settings(), "pw", connect=lambda s: FakeIMAP({"1": b"x", "2": b"y"})) == 2


def test_connection_error_is_wrapped():
    def boom(settings):
        raise ConnectionRefusedError("refused")
    with pytest.raises(mail_fetch.MailError, match="Keine Verbindung"):
        mail_fetch.test_connection(_settings(), "pw", connect=boom)


def test_settings_roundtrip_via_config(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    s = _settings(port=143, security="starttls", days_back=7, max_messages=5, folder="Bestellungen")
    mail_fetch.save_settings(s)
    assert mail_fetch.load_settings() == s
    assert "pw" not in (tmp_path / "config.json").read_text(encoding="utf-8")


class FlakyIMAP(FakeIMAP):
    """Wie FakeIMAP, aber der Inhalt von Nachricht "2" lässt sich nicht laden."""

    def uid(self, command, *args):
        if command == "FETCH" and args[0] == "2" and "HEADER" not in args[1]:
            self.commands.append((command, args))
            return "NO", [b"Nachricht nicht verfuegbar"]
        return super().uid(command, *args)


def test_single_broken_mail_does_not_abort_the_whole_fetch():
    broken_charset = _mail("Bestellung").replace(b'charset="utf-8"', b'charset="x-gibt-es-nicht"')
    server = FlakyIMAP({"1": _mail("Bestellung"), "2": _mail("Bestellung"), "3": broken_charset})
    mails = mail_fetch.fetch_orders(_settings(), "pw", connect=lambda s: server)

    by_uid = {m.uid: m for m in mails}
    assert [i.name for i in by_uid["1"].items] == ["Sanda - Band 12", "Fabiniku 14"]   # die intakte Mail zählt
    assert by_uid["2"].items == [] and "konnte nicht geladen werden" in by_uid["2"].error
    assert by_uid["3"].items == [] and "nicht gelesen werden" in by_uid["3"].error
