# Manga & Light Novel Bibliothek

[![Tests](https://github.com/Sturmschleier/Manga-Bibliothek/actions/workflows/tests.yml/badge.svg)](https://github.com/Sturmschleier/Manga-Bibliothek/actions/workflows/tests.yml)

Ein Windows-Programm, das deine Manga-, Manhwa- und Light-Novel-Sammlung in
einer lokalen Datenbank verwaltet: Bände, Lesestand, Verlage und
Erscheinungstermine – sortierbar, durchsuchbar und farbcodiert.

Hinweise zu Quellcode, Tests und dem Bau der exe stehen in
[ENTWICKLUNG.md](ENTWICKLUNG.md).

## Inhalt

1. [Überblick](#1-überblick)
2. [Installation und Start](#2-installation-und-start)
3. [Erste Schritte](#3-erste-schritte)
4. [Bedienung](#4-bedienung)
5. [Bestellungen aus E-Mails](#5-bestellungen-aus-e-mails)
6. [ISBN-Abgleich und Bestellliste](#6-isbn-abgleich-und-bestellliste)
7. [Daten und Sicherheit](#7-daten-und-sicherheit)
8. [Konfiguration](#8-konfiguration)
9. [Hilfe und Fehlersuche](#9-hilfe-und-fehlersuche)

## 1. Überblick

- **Sammlung verwalten:** alle Spalten deiner bisherigen Liste, bearbeitbar
  im Formular, dazu „+1“-Knöpfe für neue und gelesene Bände.
- **Überblick behalten:** Farbcodierung, Suche und Filter, Statistik und
  anstehende Erscheinungstermine in der Seitenleiste.
- **Bestellungen:** Bestellbestätigungen per E-Mail einlesen (Datei,
  Drag & Drop oder direkt aus dem Postfach) – bestellte und abholbereite
  Bände werden markiert.
- **ISBN-Abgleich:** sucht die ISBN des nächsten Bandes bei der Deutschen
  Nationalbibliothek (DNB) und erstellt eine Bestellliste mit Links zum
  Buchhändler.
- **VÖ-Termine:** holt die Erscheinungstermine neuer Bände von
  buchhandel.de und trägt sie rot in VÖ +1 bis VÖ +3 ein.
- **Sicher:** Änderungen werden erst beim Speichern übernommen, vor jedem
  Speichern entsteht eine Sicherung; optional zusätzlich in Google Drive.

## 2. Installation und Start

### 2.1 Fertige exe herunterladen

1. Die neueste Version unter
   [Releases](https://github.com/Sturmschleier/Manga-Bibliothek/releases/latest)
   öffnen und `MangaLibrary.exe` herunterladen.
2. Die exe in einen eigenen Ordner legen (z. B. `Dokumente\Manga`) und von
   dort starten. Python wird nicht benötigt.
3. Die exe ist nicht signiert – Windows SmartScreen kann beim ersten Start
   warnen („Weitere Informationen“ → „Trotzdem ausführen“).

Die exe legt ihre Daten **neben sich** ab (Datenbank, Konfiguration,
Protokolle, Sicherungen – siehe [Kapitel 9](#9-hilfe-und-fehlersuche)).
Deshalb immer aus diesem Ordner starten und die exe nicht allein
verschieben, sonst startet sie mit einer leeren Datenbank.

**Aktualisieren:** Programm beenden und `MangaLibrary.exe` im Ordner durch
die neue Version ersetzen. Die Daten bleiben erhalten; eine ältere
Datenbank bringt das Programm beim ersten Start automatisch auf den
aktuellen Stand. Sicherheitshalber vorher den Ordner kopieren.

### 2.2 Aus dem Quellcode starten

Voraussetzung ist Python 3.9 oder neuer. Im Programmordner:

```bash
pip install -r requirements.txt
python main.py
```

Die Google-Bibliotheken braucht nur die Google-Drive-Anbindung, `requests`
nur der ISBN-Abgleich – fehlen sie, läuft das Programm trotzdem, und nur die
jeweilige Funktion meldet einen Fehler. Die Daten liegen dann neben
`main.py`.

## 3. Erste Schritte

Beim ersten Start legt das Programm eine leere Datenbank an.

### 3.1 Bestehende Liste importieren

**Datei → CSV importieren …** und die Datei auswählen – z. B. die
ursprüngliche Liste `Manga - Besitz.csv` oder einen eigenen CSV-Export.
Danach auf **💾 Speichern** klicken.

- Titel, die schon vorhanden sind, werden übersprungen – mehrfaches
  Importieren erzeugt keine doppelten Einträge.
- Trennzeichen (Komma, Semikolon oder Tab) und Zeichensatz (UTF-8 oder das
  Windows-1252 älterer Excel-Versionen) erkennt der Import selbst.
- Die Spalten werden anhand der Kopfzeile zugeordnet, auch in anderer
  Reihenfolge. Passt die Spaltenzahl nicht, bricht der Import mit einer
  Meldung ab; ist die Kopfzeile nicht eindeutig, gilt die
  Standard-Reihenfolge – mit dem Hinweis, das Ergebnis kurz zu prüfen.
- Die Spalten „Rückstand“, „VÖ +4“ und „VÖ +5“ (aus älteren Listen) werden
  ignoriert.

Ohne Oberfläche, mit sofortigem Schreiben in die Datenbank:
`python import_csv.py "Manga - Besitz.csv"`

### 3.2 Zwischenspeicher und Speichern

Alle Änderungen – neuer Eintrag, Bearbeiten, Löschen, „+1“, CSV-Import,
Bestell-Markierungen – wirken zunächst nur im **Zwischenspeicher**. Erst
**💾 Speichern** (Strg+S) schreibt den Bestand dauerhaft in die Datenbank.

- Solange es ungespeicherte Änderungen gibt, zeigt der Fenstertitel ein
  „*“ und die Statuszeile einen Hinweis.
- Beim Schließen fragt das Programm, ob gespeichert werden soll. Schlägt
  das Speichern fehl (z. B. weil die Datei gerade von einer
  Cloud-Synchronisierung oder einem Virenscanner gesperrt ist), erscheint
  eine Meldung, die Änderungen bleiben erhalten und das Fenster bleibt
  offen.
- **↶ Rückgängig / ↷ Wiederholen** (Strg+Z / Strg+Umschalt+Z) gilt für alle
  Änderungen im Zwischenspeicher. Abgelehnte Aktionen (z. B. „+1“ über
  „Bände (bis)“ hinaus) erzeugen keinen Schritt; ein Google-Drive-Download
  setzt die Historie zurück.

## 4. Bedienung

### 4.1 Fenster, Menüs, Suche und Filter

- **Werkzeugleiste:** Rückgängig, Wiederholen, 💾 Speichern,
  ⬆ Zu Google Drive sichern, 🔍 ISBN-Abgleich / Bestellliste sowie die
  Filter.
- **Menü „Datei“:** Neuer Eintrag (Strg+N), Bearbeiten, Löschen (mit
  Rückfrage), Bei buchhandel.de suchen (Strg+B), CSV importieren und
  exportieren, Bestellungen aus E-Mail bzw. Postfach einlesen, Von Google
  Drive laden.
- **Menü „Konfigurieren“:** Farben, Konfiguration …, Postfach (IMAP) … und
  die Schalter „Nach Bearbeitung zur Zeile springen“ und „Gestoppt: keine
  Berechnung“ (siehe [Kapitel 8](#8-konfiguration)).
- **Menü „Hilfe“:** LOG-Ordner öffnen, Über … (siehe [Kapitel 9](#9-hilfe-und-fehlersuche)).

In der **Tabelle**:
- **Doppelklick** auf eine Zeile öffnet das Formular (außer auf den
  „+1“-Spalten).
- **Rechtsklick:** Bei buchhandel.de suchen, Bestell-Markierung entfernen
  (falls vorhanden), Bearbeiten, Löschen.
- **Klick auf eine Spaltenüberschrift** sortiert (erneuter Klick: absteigend).
  Datums- und Zahlenspalten werden nach ihrem Wert sortiert, nicht als Text.
  Die Spaltenbreite lässt sich am Rand der Überschrift ziehen; die
  Titelspalte passt sich an den längsten Titel an.
- **„Rückstand“** (ganz rechts) = Bände (bis) − Gelesen bis – nur angezeigt,
  nicht gespeichert. Aufsteigend sortiert stehen die Reihen mit dem
  kleinsten Leserückstand oben.

**Suche und Filter:** Die Suche oben in der Seitenleiste filtert live über
alle Spalten. Dazu kommen in der Werkzeugleiste die Filter **Verlag** und
**VÖ +1** (Beendet, TBA, Gestoppt, NA oder „Mit Datum“) sowie
**Bestellung**: „Bestellt“ (Titel hellblau), „Angekommen“ (roter Balken),
„Bestellt oder angekommen“ und „Nicht bestellt“ (keine Markierung, siehe
[Kapitel 5](#5-bestellungen-aus-e-mails)). Alle lassen sich
kombinieren. „Filter zurücksetzen“ leert Filter und Suche auf einmal.

**Bei buchhandel.de suchen** öffnet im Browser die Suche nach dem markierten
Titel (gedruckte Bücher ab dem aktuellen Jahr, nach Erscheinungsdatum
sortiert).

**Formular:** „Typ“, „Komplett“, „Beendet“ und „Verlag“ bieten eine Auswahl,
lassen sich aber frei überschreiben. Beim Übernehmen prüft das Formular die
Eingaben und nennt alle Probleme auf einmal:
- Der Titel ist Pflicht und darf nicht schon vorkommen (Groß-/Kleinschreibung
  egal) – doppelte Titel würden ISBN-Abgleich und Bestellzuordnung
  durcheinanderbringen.
- „Bände (bis)“ und „Gelesen bis“ sind leer oder ganze Zahlen, und „Gelesen
  bis“ ist nicht größer als „Bände (bis)“.
- Datumswerte (Zugang, VÖ) müssen gültig sein (TT.MM.JJJJ oder MM.JJJJ);
  Freitext wie „TBA“ oder „Band 17 11.06.2025“ bleibt erlaubt.

### 4.2 „+1“-Knöpfe

- **Bände (bis):** erhöht die Zahl um 1 und rückt die Erscheinungstermine
  eine Position nach vorn (VÖ +2 → VÖ +1, VÖ +3 → VÖ +2), denn der bisherige
  VÖ +1-Termin ist mit dem neuen Band eingelöst. Bleibt kein Termin übrig,
  wird „NA“ eingetragen. **Ausnahme:** Steht in VÖ +1 „Fortlaufend“ (Reihe
  ohne bandweisen Zeitplan), bleiben alle Termine unverändert.
- **Gelesen bis:** erhöht nur dieses Feld um 1 – aber nicht über „Bände
  (bis)“ hinaus; stattdessen erscheint ein Hinweis.

Beide wirken wie jede Änderung zunächst im Zwischenspeicher.

### 4.3 Farbcodierung

- **VÖ +1:** Beendet = Grün, TBA = Orange, Gestoppt = Rot, NA = Pink.
- **Komplett / Beendet:** Ja = Grün, Nein = Rot.
- **Verlag:** Jeder Verlag bekommt automatisch eine eigene Pastellfarbe aus
  einer Palette von 24 gut unterscheidbaren Farben. Die Farbe ergibt sich
  aus dem Namen und bleibt daher meist stabil; kommt ein Verlag hinzu, kann
  sich die Farbe eines anderen ändern, wenn beide denselben Platz
  beanspruchen. Ab 25 Verlagen wiederholen sich Farben.
- **Titel:** hellblau = nächster Band bestellt, roter Balken links = Band
  abholbereit (siehe [Kapitel 5](#5-bestellungen-aus-e-mails)).
- **Zeilen:** jede zweite Zeile ist leicht grau hinterlegt.

Die Legende steht rechts in der Statuszeile. Unter **Konfigurieren → Farben**
lässt sich jede Kategorie einzeln abschalten – dann gilt dort die normale
Zeilenfarbe.

### 4.4 Seitenleiste und Live-Log

Die Seitenleiste rechts (anfangs 15 % der Fensterbreite, am Trenner
verstellbar) zeigt:

- **Statistik:** Summe im Besitz, Summe gelesen, Differenz und Gelesen-Anteil.
- **Anzahl nach Verlag:** alle Verlage mit ihrer Titelzahl, die größten
  zuerst.
- **Anzahl nach Typ:** je Typ die Bände-Bilanz als **Gesamt · Gelesen ·
  Offen**, z. B. „Manga: 1207 · 500 · 707“.
- **Erscheinungstermine:** Termine im aktuellen, nächsten und übernächsten
  Monat – gezählt über alle VÖ-Spalten, ein Titel mit zwei Terminen im
  selben Monat zählt also doppelt.
- **Ausstehende Termine:** Termine vor dem aktuellen Monat – vermutlich
  erschienen, aber noch nicht per „+1“ nachgetragen.
- **Live-Log:** jede Änderung dieser Sitzung (Anlegen, Bearbeiten, Löschen,
  „+1“, Import, Rückgängig, Speichern …).

Alle Änderungen landen zusätzlich dauerhaft in `LOG/aenderungen.log`.
Einträge, die älter als 182 Tage sind (`log_retention_days`), wandern beim
Programmstart nach `LOG/aenderungen_archiv.log` – nichts geht verloren.

## 5. Bestellungen aus E-Mails

### 5.1 Bestellbestätigung einlesen

Es gibt drei Wege:

1. **Datei → Bestellung aus E-Mail (.eml) einlesen …** – eine oder mehrere
   `.eml`-Dateien auswählen.
2. **Drag & Drop** – `.eml`-Dateien (z. B. aus Thunderbird oder dem
   Explorer) auf das Programmfenster ziehen.
3. **Datei → Bestellungen aus Postfach abrufen …** – siehe
   [5.2](#52-postfach-abruf-imap).

Das Programm liest die Artikelliste und ordnet jeden Artikel einem Eintrag
zu: Der Artikelname beginnt mit dem Titel, danach folgt die Bandnummer
(„Sanda - Band 12“, „Fabiniku 14“). Steht noch ein Zusatz dazwischen („Togen
Anki - Teufelsblut 23“), zählt der Treffer nur, wenn die Nummer genau der
nächste Band ist. Bände, die schon im Bestand sind, werden nicht markiert.

- **Bestellt:** Der Titel wird **hellblau** markiert. Die Markierung merkt
  sich den bestellten Band (Tooltip, z. B. „Band 14 bestellt“); bei mehreren
  Bänden gilt der höchste.
- **Abholbereit:** Die Mail „Ihre Bestellung ist in Ihrer Buchhandlung
  abholbereit“ wird auf denselben Wegen erkannt und setzt zusätzlich einen
  **roten Balken** links am Titel.
- Eine Markierung verschwindet, sobald „Bände (bis)“ ihren Band erreicht –
  per „+1“ oder im Formular. Beispiel: Band 12 im Bestand, Band 14 bestellt
  – nach „+1“ auf 13 bleibt die Markierung, erst bei 14 entfällt sie. Von
  Hand geht es per Rechtsklick → „Bestellt-/Angekommen-Markierung
  entfernen“.
- Nach dem Einlesen zeigt ein Fenster, was markiert wurde; unter „Details“
  stehen Artikel ohne passenden Eintrag und Bände, die schon im Bestand
  sind. Eine defekte Mail bricht das Einlesen nicht ab, sondern wird als
  „nicht lesbar“ gemeldet.
- Die Markierungen gehören zum Eintrag: Sie lassen sich rückgängig machen,
  werden erst mit „Speichern“ dauerhaft und stehen nicht im CSV-Export.
- **Datenschutz:** Die E-Mail selbst wird nicht gespeichert – weder Adresse
  noch Bestellnummer noch Preise. Jedes Einlesen schreibt ein Protokoll
  `LOG/bestellung_einlesen_<Datum>_<Uhrzeit>.log` mit Artikelnamen und
  Bandnummern, am Ende ein eigener Abschnitt „ARTIKEL OHNE PASSENDEN
  EINTRAG“. Es bleiben die neuesten 10 Protokolle (`order_log_keep`).

### 5.2 Postfach-Abruf (IMAP)

**Konfigurieren → Postfach (IMAP) …** richtet den Zugang ein – es genügt
irgendein IMAP-Server. Vorlagen (GMX, WEB.DE, Gmail, Yahoo, iCloud,
T-Online, IONOS, Posteo, mailbox.org) füllen Server, Port und
Verschlüsselung vor. **„Verbindung testen“** prüft Server, Anmeldung und
Ordner.

- **Filter:** Ordner (Standard `INBOX`), „Absender enthält“ (Standard
  `konold`), „Betreff enthält“ (Standard `Bestellung`), Zeitraum (90 Tage)
  und höchstens 30 Mails je Abruf.
- **Abruf:** Die gefundenen Mails erscheinen zur Auswahl (Datum, Betreff,
  Artikelzahl) und werden dann wie beim Datei-Import eingelesen. Mails ohne
  Artikelliste (z. B. Versandmitteilungen) werden übersprungen; ein
  erneuter Abruf markiert nichts doppelt.
- **Passwort:** steht nie in der `config.json`. Wahlweise wird es in den
  Windows-Anmeldeinformationen gespeichert, sonst beim Abruf abgefragt und
  nur bis zum Programmende gemerkt. Bei GMX, WEB.DE, Gmail u. ä. muss der
  IMAP-Zugriff in den Kontoeinstellungen erlaubt sein, teils ist ein
  App-Passwort nötig. Anbieter, die nur OAuth2 erlauben (z. B.
  Outlook.com), funktionieren nicht.
- **Nur lesend:** Der Ordner wird schreibgeschützt geöffnet, Mails werden
  nicht als gelesen markiert, nichts wird verändert oder gelöscht. Die
  Verbindung ist verschlüsselt (SSL/TLS oder STARTTLS mit
  Zertifikatsprüfung).

## 6. ISBN-Abgleich und Bestellliste

### 6.1 Abgleich starten

Der Knopf **🔍 ISBN-Abgleich / Bestellliste** öffnet die Auswahl:

- **Nach Monat/Jahr:** alle Titel, deren VÖ +1 in diesem Monat liegt,
- **VÖ +1 = „TBA“** oder **VÖ +1 = „NA“**,
- **Bestellen bei:** Konold (Standard), Thalia oder Amazon – die Auswahl
  wird gemerkt,
- **Vorhandene ISBNs erneut prüfen:** sucht auch Titel neu, für die schon
  eine ISBN gespeichert ist (z. B. wenn ein früherer Treffer falsch war).

Für jeden Titel sucht das Programm die ISBN des nächsten Bandes („Bände
(bis)“ + 1) bei der DNB, beschränkt auf das aktuelle und das nächste Jahr.
Dabei achtet es auf den Verlag und auf den Typ (Manga oder Light Novel –
manche Reihen gibt es als beides) und übernimmt nur ISBNs mit gültiger
Prüfziffer. Der Abgleich nutzt den aktuellen Stand im Zwischenspeicher,
vorher speichern ist nicht nötig.

Er läuft im Hintergrund und kann einige Minuten dauern, weil zwischen den
Anfragen kurz gewartet wird. Das Fortschrittsfenster zeigt „Titel x von y“;
**„Abbrechen“** beendet den Abgleich nach dem laufenden Titel. Jede
gefundene ISBN wird sofort gespeichert und geht auch bei einem Abbruch nicht
verloren.

### 6.2 Ergebnis und Bestellliste

Das Ergebnisfenster zeigt eine Zusammenfassung und die fertige
**Bestellliste** (Markdown-Tabelle, chronologisch nach VÖ +1), die sich per
Knopfdruck in die Zwischenablage kopieren lässt. Alle Links sind anklickbar.

- **Sicher** ist ein Treffer, wenn Bandnummer und Verlag passen. **Unsicher**
  (bitte vor der Bestellung prüfen) steht mit Grund dabei: Verlag nicht
  bestätigt oder Bandnummer nur im Titel erkannt.
- Titel **ohne Treffer** sind **rot** hinterlegt und bekommen einen
  Suchlink – standardmäßig bei buchhandel.de, wahlweise bei manga-passion.de
  (`isbn_fallback_provider`).
- Eine gefundene ISBN gilt nur für genau diesen Band: Nach „+1“ auf „Bände
  (bis)“ verschwindet sie aus der Liste, statt für den falschen Band
  weiterverwendet zu werden. Im CSV-Export stehen keine ISBNs.

### 6.3 Sonderausgaben

Collector's-, Limited- und Variant-Editionen, Ausgaben mit Sammelschuber
oder Acryl-Aufsteller, Starter Packs, Bundles und Sammelbände (z. B.
„Massiv“, „2in1“) erkennt das Programm am DNB-Titel. Sie werden **nie** als
ISBN des Bandes übernommen – dort steht immer die normale Ausgabe –,
sondern in der Bestellliste zusätzlich aufgeführt („↳ Sonderausgabe: …“ mit
eigener ISBN und eigenem Link). Gibt es für den Band beides, sind alle
Zeilen dieses Titels mit **★** markiert und **golden** hinterlegt.

Ein Begriff zählt nicht, wenn er schon zum Reihentitel gehört („Blue Box
17“ ist für die Reihe „Blue Box“ eine normale Ausgabe); Beigaben der
normalen Erstauflage wie „mit Collector's Print“ oder „mit Farbschnitt“
gelten nicht als Sonderausgabe.

### 6.4 Log-Datei

Jeder Abgleich schreibt `LOG/isbn_abgleich_<Datum>_<Uhrzeit>.log` mit allen
DNB-Anfragen, der Zahl der Treffer, gefundenen Sonderausgaben und dem
Ergebnis je Titel – hilfreich, wenn ein Band nicht gefunden wurde (z. B.
weil die DNB den Titel anders schreibt). Der Pfad steht am Ende der
Zusammenfassung. Es bleiben die neuesten 10 Log-Dateien (`isbn_log_keep`).

### 6.4 VÖ-Termine von buchhandel.de

Der Knopf **📅 VÖ-Termine holen** (auch unter Datei) fragt für alle Serien,
bei denen neue Bände erscheinen können, die Terminliste von buchhandel.de ab
und trägt Bände **nach dem letzten besessenen Band** in VÖ +1 bis VÖ +3 ein –
Band „Bände (bis)“ + 1 nach VÖ +1, + 2 nach VÖ +2 usw. Eine Lücke (Band + 1
noch nicht angekündigt, Band + 2 schon) bricht die Zuordnung ab, damit kein
Termin in die falsche Spalte rutscht.

- **Einzelner Titel:** Rechtsklick auf einen Eintrag → **Neue VÖ-Termine
  abfragen** fragt nur diese eine Serie ab. Die Überspringregel gilt dabei
  nicht (auch bei „Komplett“ wird abgefragt); Freitext wie „Fortlaufend“
  wird trotzdem nie überschrieben.
- **Auswahl:** Vor dem Start wählst du, welche Serien abgefragt werden –
  *Alle*, *nur mit Datum in VÖ +1*, *nur TBA* oder *nur NA* –, jeweils mit
  Anzahl und geschätzter Dauer. So lässt sich die Abfrage verkürzen.
- **Übersprungen** werden Einträge mit *Komplett* = Ja sowie VÖ +1 =
  „Fortlaufend“, „Gestoppt“ oder „Beendet“. Die Spalte *Beendet* zählt nicht,
  „NA“ und „TBA“ werden immer abgefragt.
- **Neue Werte sind rot** und gelten erst nach **Speichern** (dann werden sie
  schwarz). Bis dahin lässt sich alles mit „Rückgängig“ zurücknehmen; ein
  von Hand geänderter Wert verliert die rote Farbe sofort.
- **Datumsformate:** Das VLB liefert TT.MM.JJJJ, manchmal nur MM.JJJJ. Ein
  ungenaues Datum bleibt ungenau und ersetzt nie ein genaueres. Freitext in
  VÖ +1 bis VÖ +3 (z. B. „Band 17 11.06.2025“) wird nicht überschrieben.
- **Zuordnung:** Es zählen nur Printausgaben passender Verlag, deren Titel auf
  eine Bandnummer endet. Sonderausgaben, Boxen und andere Reihen mit ähnlichem
  Titel werden ausgeschlossen. Lässt sich eine Reihe nicht eindeutig
  zuordnen, steht sie im Ergebnis unter „Nicht eindeutig“ (Details-Knopf).
- **Fair Use:** Pro Serie eine Anfrage, dazwischen 4 bis 6 Sekunden Pause, nur
  auf Knopfdruck. Nach drei Fehlern in Folge (z. B. Seite nicht erreichbar)
  wird der Abruf beendet. Die Schnittstelle von buchhandel.de ist nicht
  offiziell dokumentiert und kann sich ohne Ankündigung ändern.

## 7. Daten und Sicherheit

### 7.1 Sicherungen

- **Vor jedem Speichern** legt das Programm eine Kopie des bisherigen
  Stands im Ordner `BACKUP` an, z. B.
  `BACKUP/manga_library_2026-09-26_14-32-05-123_vor-speichern.db`. Es
  bleiben die neuesten 20 (`db_backup_keep`). Lässt sich keine Sicherung
  anlegen, fragt das Programm, ob trotzdem gespeichert werden soll.
- **Wiederherstellen:** Programm beenden und die gewünschte Sicherung als
  `manga_library.db` in den Programmordner kopieren.
- **Nur ein Programmfenster:** Ein zweiter Start wird mit einem Hinweis
  abgebrochen – zwei Fenster würden sich gegenseitig ihre Änderungen
  überschreiben. Nach einem Absturz gibt der nächste Start die Sperre
  automatisch frei.

### 7.2 Google Drive

Die Datenbank lässt sich in Google Drive sichern (**⬆ Zu Google Drive
sichern**) und von dort laden (**Datei → Von Google Drive laden**). Sie
liegt dort im Ordner `MangaLibrary`; es wird immer dieselbe Datei
aktualisiert.

**Einrichten (einmalig):**
1. In der [Google Cloud Console](https://console.cloud.google.com/) ein
   Projekt anlegen (oder ein bestehendes nutzen).
2. Unter **APIs & Dienste → Bibliothek** die **Google Drive API**
   aktivieren.
3. Unter **APIs & Dienste → OAuth-Zustimmungsbildschirm** einen Bildschirm
   vom Typ „Extern“ anlegen; für den privaten Gebrauch reicht es, dich selbst
   als Testnutzer einzutragen.
4. Unter **APIs & Dienste → Zugangsdaten → Zugangsdaten erstellen →
   OAuth-Client-ID** den Typ **Desktop-App** wählen.
5. Die heruntergeladene JSON-Datei als `credentials.json` neben die exe
   (bzw. neben `main.py`) legen.

Beim ersten Sichern öffnet sich ein Browserfenster zur Anmeldung; danach
merkt sich das Programm die Anmeldung in `token.json`. Ist sie abgelaufen,
wird neu angemeldet. Die Anmeldung muss innerhalb von 5 Minuten
abgeschlossen werden.

- **Sichern:** Ungespeicherte Änderungen werden vorher gespeichert (mit
  Rückfrage), denn hochgeladen wird die Datenbankdatei.
- **Laden:** ersetzt die lokale Datenbank **und** den Zwischenspeicher –
  ungespeicherte Änderungen gehen verloren (mit Warnung). Die Datei wird
  zuerst vollständig geladen und geprüft; erst dann wird die lokale
  Datenbank gesichert (`…_vor-download.db`) und ersetzt. Bricht der Download
  ab, bleibt die lokale Datenbank unverändert.
- Beides läuft im Hintergrund, das Fenster bleibt bedienbar.

⚠️ `credentials.json` und `token.json` sind persönliche Zugangsdaten – nicht
weitergeben.

### 7.3 CSV-Export

**Datei → CSV exportieren …** speichert den aktuellen Stand (auch
ungespeicherte Änderungen) mit allen Spalten und sprechenden Überschriften –
z. B. für Excel oder als Kopie außerhalb der Datenbank. Getrennt wird mit
**Semikolon**, damit Excel mit deutschen Einstellungen die Datei direkt in
Spalten öffnet (`csv_delimiter`). ISBNs, Bestell-Markierungen und
„Rückstand“ sind nicht enthalten. Ein Export lässt sich wieder importieren.

## 8. Konfiguration

Die Einstellungen stehen in `config.json` im Programmordner.
**Konfigurieren → Konfiguration …** öffnet sie zum Bearbeiten; die meisten
Änderungen wirken sofort. Beim Speichern prüft der Editor Syntax, Typ und
Wert der bekannten Einstellungen (z. B. `true`/`false` statt `"false"`,
ganze Zahlen, `{isbn}` in der Link-Vorlage) und speichert erst, wenn alles
passt.

| Schlüssel | Bedeutung | Standard |
|---|---|---|
| `isbn_shop_name` | Name des Standard-Buchhändlers für gefundene ISBNs | `Konold` |
| `isbn_shop_url_template` | Link-Vorlage des Standard-Buchhändlers, `{isbn}` wird ersetzt | Konold-Shop |
| `isbn_shop_active` | Zuletzt gewählter Buchhändler (`Thalia`, `Amazon`; leer = Standard) | `""` |
| `isbn_fallback_provider` | Suchlink ohne Treffer: `buchhandel.de` oder `manga-passion` | `buchhandel.de` |
| `follow_selection_after_edit` | Nach einer Änderung zur Zeile springen (sonst bleibt die Scroll-Position) | `true` |
| `exclude_gestoppt_from_stats` | Titel mit VÖ +1 = „Gestoppt“ nicht in Statistik und Typ-Bilanz einrechnen | `false` |
| `sidebar_width_fraction` | Anteil der Seitenleiste an der Fensterbreite – wirkt beim nächsten Start | `0.15` |
| `colors_enabled` | Farbcodierung je Kategorie: `voe1`, `komplett_beendet`, `verlag`, `bestellt`, `angekommen` | alle `true` |
| `csv_delimiter` | Trennzeichen des CSV-Exports: `";"`, `","` oder `"\t"` (Tab) | `";"` |
| `db_backup_keep` | So viele Datenbank-Sicherungen bleiben in `BACKUP/` | `20` |
| `isbn_log_keep` | So viele Log-Dateien des ISBN-Abgleichs bleiben | `10` |
| `order_log_keep` | So viele Log-Dateien von „Bestellung einlesen“ bleiben | `10` |
| `log_retention_days` | Einträge des Änderungsprotokolls, die älter sind, wandern ins Archiv | `182` |

Die Zugangsdaten und Filter für den Postfach-Abruf stehen ebenfalls hier,
werden aber über **Konfigurieren → Postfach (IMAP) …** eingestellt.

Die beiden Schalter „Nach Bearbeitung zur Zeile springen“ und „Gestoppt:
keine Berechnung“ im Menü „Konfigurieren“ sowie die Farben ändern die
entsprechenden Werte direkt. „Gestoppt: keine Berechnung“ betrifft nur
Summen und Bilanzen, nicht die reinen Anzahl-Listen.

Die Datei lässt sich auch mit einem Texteditor bearbeiten (am besten bei
geschlossenem Programm). Ist sie beschädigt, meldet das Programm das beim
Start und verwendet die Standardwerte; beim nächsten Ändern einer
Einstellung wird die beschädigte Datei als `config.json.defekt`
aufbewahrt.

## 9. Hilfe und Fehlersuche

**Hilfe → Über …** zeigt die Programmversion, den Link zum Quellcode, den
Datenordner (per Klick im Explorer öffnen) und alle verwendeten Module mit
Version, Zweck und Lizenz. **„In Zwischenablage kopieren“** liefert das
Ganze als Text – praktisch für eine Fehlermeldung.

**Hilfe → LOG-Ordner öffnen** öffnet den Ordner `LOG` mit allen
Protokollen direkt im Explorer.

**Im Datenordner** (neben der exe bzw. neben `main.py`):

| Datei / Ordner | Inhalt |
|---|---|
| `manga_library.db` | die Datenbank mit deiner Sammlung |
| `config.json` | Einstellungen (siehe [Kapitel 8](#8-konfiguration)) |
| `credentials.json`, `token.json` | Google-Drive-Zugang (nur wenn eingerichtet) |
| `BACKUP/` | Sicherungen der Datenbank |
| `LOG/aenderungen.log`, `LOG/aenderungen_archiv.log` | Änderungsprotokoll |
| `LOG/isbn_abgleich_*.log`, `LOG/bestellung_einlesen_*.log` | Protokolle von ISBN-Abgleich und Bestellungen |
| `LOG/fehler.log` | unerwartete Fehler mit allen Details |
| `manga_library.db.lock` | Sperre gegen einen zweiten Programmstart (nur während das Programm läuft) |

**Häufige Meldungen:**
- **„Die Bibliothek ist bereits in einem anderen Programmfenster
  geöffnet.“** – das Programm läuft schon; das vorhandene Fenster verwenden.
- **„Speichern fehlgeschlagen“** – die Datenbank ist vermutlich gerade von
  einem anderen Programm gesperrt (Cloud-Synchronisierung, Virenscanner).
  Die Änderungen bleiben erhalten; später erneut speichern.
- **„config.json ist beschädigt“** – siehe [Kapitel 8](#8-konfiguration).
- **Unerwarteter Fehler** – die Meldung nennt `LOG/fehler.log`; die Datei
  enthält die Details für eine Fehlersuche.
