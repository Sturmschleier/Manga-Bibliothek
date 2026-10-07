# Code-Signing-Richtlinie (ENTWURF)

> **Entwurf:** Diese Seite erst nach der Zusage der SignPath Foundation in
> `docs/code-signing-policy.md` umbenennen und von der README verlinken. Vorher
> darf die Aussage zur kostenlosen Signatur nicht veröffentlicht werden, weil sie
> noch nicht stimmt. Die Stellen in `<…>` vor der Veröffentlichung ausfüllen.

## Signatur

Kostenlose Code-Signatur durch [SignPath.io](https://signpath.io), Zertifikat von
der [SignPath Foundation](https://signpath.org).

Signiert wird ausschließlich `MangaLibrary.exe` in den Releases dieses
Repositories. Die exe wird von GitHub Actions aus dem veröffentlichten Quellcode
gebaut (Workflow `.github/workflows/release.yml`, Tag `v…` auf `main`); es wird
nichts signiert, was nicht aus diesem Quellcode stammt.

## Rollen

| Rolle | Person |
|---|---|
| Committer und Reviewer | <GitHub-Name, z. B. Sturmschleier> |
| Freigabe (Approver) der Signaturanfragen | <GitHub-Name> |

## Datenschutz

Dieses Programm sendet keine Informationen an andere vernetzte Systeme, außer
wenn der Benutzer es ausdrücklich verlangt: ISBN-Abgleich (Deutsche
Nationalbibliothek), Abfrage der Erscheinungstermine (buchhandel.de),
Sicherung in Google Drive und Abruf von Bestellbestätigungen per IMAP. Alle
diese Funktionen starten nur auf Knopfdruck. Zugangsdaten verbleiben auf dem
eigenen Rechner (Passwörter in den Windows-Anmeldeinformationen).
