# Manga & Light Novel Bibliothek

[![Tests](https://github.com/Sturmschleier/Manga-Bibliothek/actions/workflows/tests.yml/badge.svg)](https://github.com/Sturmschleier/Manga-Bibliothek/actions/workflows/tests.yml)

Ein Desktop-Programm (Python + Qt/PySide6), das deine Manga-, Manhwa- und
Light-Novel-Sammlung in einer lokalen Datenbank verwaltet – mit allen
Spalten aus deiner bisherigen Liste, grafisch bearbeitbar, sortierbar,
durchsuchbar und farbcodiert. Optional kann die Datenbank in Google Drive
gesichert und von dort wieder geladen werden.

Die Tabelle nutzt eine echte, virtualisierte Qt-Tabellenansicht: Es werden
nur für die gerade sichtbaren Zeilen tatsächlich Zeichenkosten fällig,
unabhängig davon, wie viele Titel die Sammlung insgesamt enthält. Das
macht auch den Programmstart bei größeren Sammlungen spürbar schneller
(frühere Versionen bauten noch für jede Zeile eigene Bedienelemente auf).

## Wichtig: Zwischenspeicher statt Sofort-Speichern

Alle Änderungen – neuer Eintrag, Bearbeiten, Löschen, die „+1“-Buttons,
CSV-Import – wirken zunächst **nur im Arbeitsspeicher**, nicht in der
Datenbankdatei. Erst ein Klick auf **„💾 Speichern“** schreibt den
gesamten Bestand dauerhaft in `manga_library.db`.

- Solange ungespeicherte Änderungen bestehen, zeigt der Fenstertitel ein
  „ *“ und die Statuszeile unten „— ungespeicherte Änderungen“.
- Beim Schließen des Fensters wird nachgefragt, ob gespeichert werden soll.
- Vor einem Google-Drive-Upload wird ebenfalls zuerst nach dem Speichern
  gefragt, da hochgeladen wird, was in der Datenbankdatei steht.
- Ein Google-Drive-Download ersetzt die lokale Datenbank **und** den
  Zwischenspeicher – nicht gespeicherte Änderungen gehen dabei verloren
  (mit Warnung vorher).
- Schlägt das Speichern fehl (z. B. weil die Datei gerade von einer
  Cloud-Synchronisierung oder einem Virenscanner gesperrt ist), erscheint
  eine Meldung und die Änderungen bleiben im Zwischenspeicher. Das gilt
  auch beim Beenden: Das Fenster bleibt dann offen, statt die Änderungen zu
  verwerfen.

## Sicherungen & Schutz vor Datenverlust

- **Sicherung vor jedem Speichern:** Bevor die Datenbank überschrieben
  wird, legt das Programm eine Kopie des bisherigen Stands im Ordner
  **`BACKUP`** neben der Datenbank an, z. B.
  `BACKUP/manga_library_2026-09-26_14-32-05-123_vor-speichern.db`. Es
  bleiben nur die neuesten **20** Sicherungen liegen (`db_backup_keep` in
  der `config.json`, mindestens 1). Zum Wiederherstellen das Programm
  beenden und die gewünschte Sicherung als `manga_library.db` in den
  Programmordner kopieren. Lässt sich keine Sicherung anlegen, fragt das
  Programm, ob trotzdem gespeichert werden soll.
- **Google-Drive-Download:** Die Datei wird zuerst vollständig in eine
  temporäre Datei geladen und geprüft (intakte SQLite-Datenbank mit
  Bibliotheks-Daten). Erst dann wird die bisherige lokale Datenbank
  gesichert (`…_vor-download.db`) und ersetzt. Bricht der Download ab oder
  ist die Datei unbrauchbar, bleibt die lokale Datenbank unverändert.
- **Nur ein Programmfenster:** Ein zweiter Start, während das Programm
  bereits läuft, wird mit einem Hinweis abgebrochen – zwei Fenster hätten
  getrennte Zwischenspeicher, und das zuletzt speichernde würde die
  Änderungen des anderen überschreiben. Dazu legt das Programm eine
  Sperrdatei `manga_library.db.lock` an; nach einem Absturz wird sie beim
  nächsten Start automatisch übernommen.
- **Unerwartete Fehler** werden als Meldung angezeigt und mit allen
  Details in `LOG/fehler.log` festgehalten (in der `.exe` gäbe es sonst
  keinerlei Hinweis).

## Farbcodierung

- **VÖ +1:** Beendet = helles Grün, TBA = helles Orange, Gestoppt = helles
  Rot, NA = Pink (wird automatisch eingetragen, siehe unten).
- **Komplett / Beendet:** Ja = dasselbe Grün, Nein = dasselbe Rot.
- **Verlag:** jeder Verlag bekommt automatisch eine eigene Pastellfarbe aus
  einer festen, gut unterscheidbaren Palette (24 Farben) – keine zwei
  vorhandenen Verlage teilen sich eine Farbe. Neue Verlage erhalten ohne
  weiteres Zutun eine noch freie Farbe; bei mehr als 24 Verlagen müssen
  sich Farben wiederholen. Da die Farben aus dem Namen abgeleitet werden,
  bleiben sie im Normalfall stabil; beim Hinzufügen eines Verlags kann sich
  aber die Farbe eines anderen Verlags ändern, wenn beide denselben
  Palettenplatz beanspruchen.
- **Zeilen:** jede zweite Zeile ist leicht hellgrau hinterlegt.

Eine Legende dazu steht direkt unter der Werkzeugleiste im Programm.

## „+1“-Buttons

- **Bände (bis):** erhöht die Zahl um 1 und verschiebt gleichzeitig die
  VÖ-Termine eine Position nach vorn (VÖ+2 → VÖ+1, VÖ+3 → VÖ+2, da
  der bisherige VÖ+1-Termin durch den neuen Band eingelöst wurde). Sind
  danach keine Termine mehr vorhanden, wird „NA“ (pink) in VÖ+1
  eingetragen. **Ausnahme:** Steht in VÖ+1 der Text „Fortlaufend“ (Reihe
  ohne festen, bandweise weiterrückenden Zeitplan), wird nichts
  verschoben – VÖ+1 bleibt auf „Fortlaufend“ stehen, VÖ+2 und VÖ+3 bleiben
  unangetastet.
- **Gelesen bis:** erhöht nur dieses eine Feld um 1. Lässt sich nicht über
  „Bände (bis)“ hinaus erhöhen – man kann nicht mehr Bände gelesen haben,
  als man besitzt; ein Hinweis erscheint stattdessen, ohne den Wert zu
  ändern.

Beide Aktionen landen wie jede andere Änderung zunächst im Zwischenspeicher.

## ISBN-Abgleich & Bestellliste

Über den Button **„🔍 ISBN-Abgleich / Bestellliste“** öffnet sich ein
Fenster mit drei Auswahlmöglichkeiten, welche Titel geprüft werden sollen:

- **Nach Monat/Jahr (VÖ +1):** alle Titel, deren VÖ +1 im gewählten Monat
  liegt (wie bisher, mit Monat/Jahr-Eingabefeldern).
- **Alle Titel mit VÖ +1 = „TBA“**
- **Alle Titel mit VÖ +1 = „NA“**

Dazu die Option **„Vorhandene ISBNs erneut prüfen (überschreiben)“**
(standardmäßig deaktiviert): Titel, für die es bereits einen
ISBN-Cache-Eintrag für den aktuellen Band-Stand gibt, werden normalerweise
übersprungen, um die DNB nicht unnötig erneut abzufragen. Diese Option
erzwingt eine frische Suche auch für diese Titel und überschreibt den
Cache-Eintrag – sinnvoll z. B., wenn ein früherer Treffer falsch war
(etwa durch eine seitdem verbesserte Zuordnungslogik) oder sich bei der
DNB etwas geändert haben könnte.

Nach dem Start:

1. Für die ausgewählten Titel wird die ISBN des nächsten Bandes
   (`Bände (bis) + 1`) bei der Deutschen Nationalbibliothek (DNB) gesucht
   – eingeschränkt auf Bücher, die im **aktuellen Kalenderjahr oder dem
   Folgejahr** erschienen sind (automatisch anhand des Systemdatums
   ermittelt, kein fester Jahreswert). Ist ein Verlag hinterlegt, wird
   zuerst direkt danach eingeschränkt gesucht (DNB-Index `vlg`
   „Verleger/Firma, Ort“; die DNB liefert pro Anfrage maximal 20 Treffer –
   bei umfangreichen/gleichnamigen Reihen kann der gesuchte Band sonst
   außerhalb dieser ersten 20 liegen); findet das nichts, folgt
   automatisch ein Fallback ohne Verlagseinschränkung. Gesucht wird nach
   **allen Wörtern des Titels oder der exakten Wortfolge**: Die Wortfolge
   allein findet Titel mit Gedankenstrich oder Doppelpunkt nicht, sobald die
   DNB sie etwas anders schreibt („Nura – Herr der Yokai“ gegenüber „Nura -
   Herr der Yokai“, „NieR:Automata“), die Wörtersuche allein verfehlt
   dagegen Titel, die die DNB als ein Wort führt („Re:Zero“). Zeichen, die
   in der DNB-Suchsprache eine Sonderbedeutung haben (`"`, `\`, `*`, `?`,
   `^`), werden aus dem Titel entfernt – ein „?“ im Titel wirkte sonst als
   Platzhalter und fand gar nichts.

   **Bandnummer:** Maßgeblich sind die Felder, in denen die DNB die
   Bandzählung eigens führt (MARC `245$n`, `490$v`/`830$v` u. a.). Eine
   Zahl im Reihentitel („Kaiju No. 8“, „7 Seeds“) gilt so nicht als
   Bandnummer. Nur wenn ein Datensatz keine solchen Felder hat, wird der
   Titeltext durchsucht (z. B. „Konosuba! … Light Novel 10“); die Zahl muss
   dort öfter vorkommen als im Reihentitel selbst. Datensätze mit Bandfeld
   haben Vorrang – so gewinnt der reguläre Band vor Sonderausgaben wie
   „Band 16-20 im Sammelschuber“. Führende Nullen spielen keine Rolle
   („07“ = 7). Übernommen wird nur eine ISBN mit gültiger Prüfziffer.

   **Sonderausgaben:** Collector's/Limited/Variant Edition, Ausgaben mit
   (Sammel-)Schuber oder Acryl-Aufsteller, Starter Packs, Bundles,
   Sammelbände („Massiv“, „2in1“) und als „Sonderausgabe“ bezeichnete
   Ausgaben werden am DNB-Titel bzw. an der Ausgabebezeichnung erkannt. Sie
   werden **nie** als ISBN des Bandes übernommen – dort steht immer die
   normale Ausgabe –, sondern zusätzlich aufgeführt. Ein Begriff zählt nur,
   wenn er nicht schon im eigenen Reihentitel steht („Blue Box 17“ ist für
   die Reihe „Blue Box“ eine normale Ausgabe). Beigaben der normalen
   Erstauflage („mit Collector's Print als Extra“, „mit Farbschnitt“) gelten
   nicht als Sonderausgabe. Gezeigt werden die Sonderausgaben des
   eingetragenen Verlags; kommt dieser unter den DNB-Treffern gar nicht vor
   (Verlag im Eintrag vermutlich veraltet), alle.

   Manche Reihen
   (z. B. Konosuba!) erscheinen sowohl als Manga als auch als Light Novel,
   teils sogar beim selben Verlag – Verlag allein reicht dann nicht zur
   Unterscheidung. Deshalb wird zusätzlich anhand des Feldes „Typ“ des
   Eintrags geprüft: Bei „Light Novel“ muss der DNB-Titel den Begriff
   „Light Novel“ explizit enthalten (üblich bei deutschen
   Light-Novel-Ausgaben), bei „Manga“/„Manhwa“ wird ein Treffer
   ausgeschlossen, dessen Titel „Light Novel“ enthält.
2. Gefundene ISBNs der normalen Ausgabe werden in einer eigenen Tabelle
   `isbn_cache` gespeichert (Schlüssel: Titel + der Band-Stand „Bände
   (bis)“, für den gesucht wurde), Sonderausgaben mit demselben Schlüssel
   in `isbn_sonderausgaben` (auch wenn es noch keine normale Ausgabe gibt;
   eine erneute Suche ersetzt sie). Titel, für die bisher nur eine
   Sonderausgabe bekannt ist, werden beim nächsten Abgleich erneut
   gesucht. ISBNs, die eine frühere Programmversion noch ohne diese
   Unterscheidung gespeichert hat, lassen sich mit „Vorhandene ISBNs
   erneut prüfen“ korrigieren. Die ISBNs werden auf den in der
   Konfiguration hinterlegten
   Online-Buchhändler verlinkt (Standard: Konold,
   `isbn_shop_name`/`isbn_shop_url_template` in `config.json` – siehe
   Abschnitt „Zentrale Konfiguration“). Im Dialog „ISBN-Abgleich /
   Bestellliste“ gibt es dafür das Dropdown **„Bestellen bei:“**, in dem
   alternativ **Thalia** (`https://www.thalia.de/suche?sq=<ISBN>`) oder
   **Amazon** (`https://www.amazon.de/s?k=<ISBN>`) gewählt werden kann; die Auswahl wird dauerhaft
   gemerkt (`isbn_shop_active`) und in der Bestellliste als Zeile
   „Buchhändler: …“ ausgewiesen. Anders als in einer früheren
   Version übersteht die ISBN dadurch ein normales „💾 Speichern“ – sie
   bezieht sich aber weiterhin nur auf genau diesen Band-Stand: Ein
   „+1“-Klick auf „Bände (bis)“ lässt sie automatisch aus der
   Bestellliste verschwinden (der Cache-Eintrag „passt“ dann nicht mehr),
   statt eine veraltete ISBN für den falschen Band weiterzuverwenden. Die
   ISBN ist weiterhin nicht Teil des CSV-Exports.
3. Wurde für einen Titel keine ISBN gefunden, führt die Bestellliste
   stattdessen einen Fallback-Suchlink – standardmäßig eine Suche auf
   **buchhandel.de** (gedruckte Bücher, ab dem aktuellen Kalenderjahr,
   nach Erscheinungsdatum sortiert). Alternativ lässt sich über
   `isbn_fallback_provider` in `config.json` auf **manga-passion.de**
   umstellen.
4. Ein **eigenes Ergebnisfenster** öffnet sich mit einer Zusammenfassung
   (wie viele automatisch gefunden wurden, wie sicher der Treffer war) und
   einer fertigen **Bestellliste** (Markdown-Tabelle mit direkten
   Konold-Links, chronologisch nach VÖ +1 sortiert), die sich per
   Knopfdruck in die Zwischenablage kopieren lässt. **Sicher** ist ein
   Treffer, wenn Bandfeld und Verlag passen; als **unsicher** (bitte vor
   der Bestellung prüfen) werden Treffer mit Grund aufgeführt, wenn der
   Verlag nicht bestätigt ist oder die Bandnummer nur im Titel erkannt
   wurde. Unter jedem Titel stehen seine Sonderausgaben als eigene Zeilen
   („↳ Sonderausgabe: …“ mit eigener ISBN und Bestell-Link). Gibt es für
   den Band **eine normale und eine Sonderausgabe**, sind alle Zeilen dieses
   Titels mit **★** gekennzeichnet und im Ergebnisfenster **golden**
   hinterlegt – auch in der Zusammenfassung, die die Sonderausgaben
   zusätzlich auflistet.

Der Abgleich arbeitet mit dem aktuellen Stand im Zwischenspeicher – auch
mit noch nicht gespeicherten Änderungen –, vorher speichern ist also nicht
nötig. In die Datenbankdatei schreibt er nur die ISBN-Tabellen, nie die
Einträge selbst. Titel ohne automatischen Treffer werden im Ergebnisfenster rot
hervorgehoben und mit einem Suchlink des konfigurierten Fallback-Anbieters
(Standard: buchhandel.de, siehe `isbn_fallback_provider`) zur manuellen
Prüfung aufgelistet – so sind sie auf einen Blick von den automatisch
gefundenen Treffern zu unterscheiden. Alle Links im Ergebnisfenster
(Buchhändler- wie Fallback-Links) sind anklickbar und öffnen sich
direkt im Standardbrowser.

Der Abgleich läuft im Hintergrund und kann je nach Anzahl der Titel
einige Minuten dauern (aus Rücksicht auf die DNB wird zwischen den
Anfragen kurz gewartet). Das Fortschrittsfenster zeigt „Titel x von y“
und hat einen Knopf **„Abbrechen“**: Der gerade laufende Titel wird noch
fertig geprüft, danach erscheint das Ergebnisfenster mit den bis dahin
geprüften Titeln (im Fenstertitel als „abgebrochen“ gekennzeichnet).
Jede gefundene ISBN wird sofort gespeichert – bei einem Abbruch oder
Absturz gehen bereits gefundene ISBNs nicht verloren.

Die DNB-Antworten werden über eine echte XML-Bibliothek
(`xml.etree.ElementTree`, Python-Standardbibliothek) ausgewertet statt per
regulärem Ausdruck – robuster gegenüber Formatierungsdetails wie
Namespace-Präfixen. Meldet die DNB einen Fehler (z. B. eine ungültige
Anfrage), steht die Meldung im Log, statt lautlos „0 Treffer“ zu melden.

### Log-Datei

Jeder Abgleich schreibt zusätzlich eine vollständige Log-Datei in einen
Ordner **`LOG`** neben der `.exe` (bzw. neben `main.py` im Quellcode-
Betrieb). Der Dateiname enthält Datum und Uhrzeit, z. B.
`LOG/isbn_abgleich_2026-09-04_14-32-05-123.log`. Es bleiben nur die neuesten
**10** Logdateien liegen – ältere werden nach jedem Abgleich und beim
Programmstart automatisch gelöscht. Die Anzahl ist in der `config.json`
über `isbn_log_keep` einstellbar (mindestens 1).

Darin steht für **jeden** durchsuchten Titel:
- jede abgesetzte DNB-SRU-Anfrage (CQL-Query und vollständige URL) – bei
  bekanntem Verlag also die verlagseingeschränkte Anfrage sowie ggf. die
  Fallback-Anfrage ohne Verlag
- die Anzahl der gefundenen DNB-Records je Anfrage und wie viele davon zur
  Bandnummer passten (getrennt nach „im Bandfeld“ und „nur im Titeltext“,
  dazu die Zahl der Sonderausgaben) sowie jede gefundene Sonderausgabe
  mit ISBN und DNB-Titel
- eine Fehlermeldung der DNB, falls die Anfrage abgelehnt wurde
- das Ergebnis (gefundene ISBN inkl. Zuordnungssicherheit, oder „kein
  Treffer“) – bei einem Abbruch außerdem, nach wie vielen Titeln

Das ist besonders hilfreich, um bei nicht gefundenen Bänden nachzuvoll-
ziehen, ob z. B. der Titel bei der DNB anders geschrieben ist oder die
Bandnummer im Katalog fehlt. Der Pfad der jeweils erzeugten Log-Datei
steht auch am Ende der Zusammenfassung im Ergebnisfenster.

## Voraussetzungen

- Python 3.9 oder neuer

## Installation & Start (aus dem Quellcode)

```bash
cd mangalib
pip install -r requirements.txt
python main.py
```

(PySide6 wird für die Oberfläche selbst benötigt. Die Google-Bibliotheken
werden nur für die Google-Drive-Anbindung benötigt, `requests` für den
ISBN-Abgleich. Fehlen Letztere, funktioniert das Programm trotzdem – die
jeweilige Funktion zeigt dann nur eine Fehlermeldung.)

Beim ersten Start wird automatisch eine leere Datenbank
`manga_library.db` im Programmordner angelegt.

**Schema-Änderung „VÖ +4 / VÖ +5 entfernt“:** Es gibt nur noch die Spalten
VÖ +1 … VÖ +3. Eine bestehende Datenbank wird beim nächsten Start
automatisch migriert (Spalten `voe_4`/`voe_5` werden gelöscht). Vorher
legt das Programm einmalig eine Sicherung `manga_library.db.vor-schema-v2.bak`
neben der Datenbank an, falls diese Spalten noch existieren. Ein
Google-Drive-Download einer älteren Sicherung wird ebenfalls migriert.

## Bestehende Liste importieren

Deine persönliche Liste `Manga - Besitz.csv` liegt lokal in diesem Ordner,
ist aber per `.gitignore` vom Repository ausgeschlossen (nicht auf GitHub).

- **In der Oberfläche:** Menü **Datei → CSV importieren …** → Datei auswählen. Die
  Einträge landen im Zwischenspeicher – **danach auf „💾 Speichern“
  klicken**, damit sie dauerhaft übernommen werden.
- **Über die Kommandozeile** (schreibt sofort in die Datenbank, ohne GUI):
  `python import_csv.py "Manga - Besitz.csv"`

Der Import überspringt Titel, die bereits vorhanden sind – ein mehrfacher
Import erzeugt also keine Duplikate.

Trennzeichen (Komma, Semikolon oder Tab) und Zeichensatz (UTF-8 oder das
von älteren Excel-Versionen verwendete Windows-1252) erkennt der Import
selbst – sowohl die ursprüngliche Liste (Komma) als auch eigene Exporte
(Semikolon) lassen sich einlesen.

Die Kopfzeile der CSV-Datei wird geprüft: Erkennt das Programm sowohl die
Beschriftungen der ursprünglichen Liste als auch die des CSV-Exports
(auch bei vertauschter Spaltenreihenfolge), werden die Spalten automatisch
korrekt zugeordnet. Passt die Spaltenanzahl nicht zur erwarteten Anzahl,
wird der Import mit einer klaren Fehlermeldung abgebrochen, statt
möglicherweise falsche Daten in die falschen Felder zu schreiben. Lässt
sich die Kopfzeile nicht eindeutig erkennen, wird der Import trotzdem mit
der Standard-Reihenfolge versucht – mit einem Hinweis, das Ergebnis kurz
zu prüfen. Eine „Rückstand“-Spalte in der Datei (egal an welcher
Position) wird erkannt und komplett ignoriert, statt den Import deswegen
abzulehnen – sie ist eine reine Anzeige-/Berechnungsspalte und nie Teil
des gespeicherten Datenmodells. Ebenso werden „VÖ +4“ und „VÖ +5“ ignoriert
(diese Spalten gibt es nicht mehr, siehe unten) – ältere CSV-Dateien mit
14 Spalten, auch die ursprüngliche `Manga - Besitz.csv`, lassen sich also
weiterhin importieren; die Inhalte dieser beiden Spalten werden verworfen.

## Bestellung aus E-Mail einlesen

Es gibt drei Wege, die Bestellbestätigung ins Programm zu bekommen:

1. **Datei → Bestellung aus E-Mail (.eml) einlesen …** – eine oder mehrere
   `.eml`-Dateien auswählen.
2. **Drag & Drop** – `.eml`-Dateien (z. B. direkt aus Thunderbird oder
   dem Explorer) einfach auf das Programmfenster ziehen; mehrere Dateien
   auf einmal sind möglich.
3. **Datei → Bestellungen aus Postfach abrufen …** – holt die Mails direkt
   aus dem E-Mail-Postfach, siehe Abschnitt „Postfach-Abruf“ unten.

Das Programm liest die Artikelliste (Name, Anzahl, Preis) und ordnet jeden Artikel einem
Eintrag zu: Der Artikelname muss mit dem Titel beginnen, danach folgt die
Bandnummer („Sanda - Band 12“, „Fabiniku 14“). Steht noch ein Zusatz
zwischen Titel und Nummer („Togen Anki - Teufelsblut 23“), zählt der Treffer
nur, wenn die Nummer genau „Bände (bis)“ + 1 ist. Ist der bestellte Band
nicht größer als „Bände (bis)“, gilt er als schon vorhanden und wird nicht
markiert.

- Zugeordnete Titel werden in der Tabelle **hellblau am Titel** markiert
  (Legende unten: „Titel bestellt“). Nach dem Einlesen zeigt ein Fenster,
  wie viele Titel markiert wurden und – unter „Details“ – welche Artikel
  keinem Eintrag zugeordnet werden konnten oder schon im Bestand sind.
- Die Markierung merkt sich **den bestellten Band** (Tooltip über dem
  Titel, z. B. „Band 14 bestellt“). Stehen mehrere Bände desselben Titels
  in einer Bestellung, gilt der höchste; eine spätere Bestellung eines
  höheren Bandes hebt die Markierung entsprechend an.
- **Abholbereit/angekommen:** Kommt später die Mail „Ihre Bestellung ist in
  Ihrer Buchhandlung abholbereit“, wird sie auf denselben Wegen (Datei,
  Drag & Drop, Postfach) erkannt – an der Struktur der Artikeltabelle, nicht
  am Betreff – und der Titel bekommt zusätzlich einen **hellroten Balken
  links** in der Titelzelle (Legende: „angekommen“). Die hellblaue
  Bestell-Markierung bleibt dabei erhalten, beide Markierungen können also
  gleichzeitig sichtbar sein.
- Eine Markierung verschwindet, sobald „Bände (bis)“ ihren Band erreicht –
  per **+1** oder beim Hochsetzen im Bearbeiten-Formular. Beispiel: Band 12
  im Bestand, Band 14 bestellt – ein „+1“ auf 13 lässt die Markierung
  stehen, erst bei 14 entfällt sie. Von Hand entfernen geht per Rechtsklick
  auf die Zeile → „Bestellt-/Angekommen-Markierung entfernen“.
- Markierungen aus früheren Programmversionen (dort nur „ja/nein“) werden
  beim ersten Start automatisch auf „nächster Band“ (`Bände (bis)` + 1)
  umgestellt – genau das bedeuteten sie bisher.
- Eine einzelne defekte oder ungewöhnliche Mail (z. B. unbekannter
  Zeichensatz) bricht den Import nicht ab: Sie wird als „nicht lesbar“
  gemeldet, die übrigen Mails werden trotzdem ausgewertet.
- **Ein-/Ausschalten:** Unter *Konfigurieren → Farben* lassen sich
  „Titel bestellt (hellblau)“ und „Titel angekommen (roter Balken links)“
  wie die übrigen Farbcodierungen einzeln an- und ausschalten
  (`colors_enabled` → `bestellt` / `angekommen` in der `config.json`).
  Ausgeschaltet bleiben die Markierungen im Datenbestand erhalten, werden
  nur nicht angezeigt.
- Die Markierung ist ein normaler Teil des Eintrags: sie wirkt auf
  Rückgängig/Wiederholen, wird erst mit „💾 Speichern“ dauerhaft und steht
  in der Datenbank (Felder `bestellt` und `angekommen`), aber nicht im
  CSV-Export.
- **Die E-Mail selbst wird nicht gespeichert.** Sie wird nur gelesen und im
  Speicher ausgewertet; weder Adresse noch Bestellnummer noch Preise werden
  übernommen. Im Live-Log/Änderungsprotokoll landen nur die markierten Titel.
- **Eigene Log-Datei je Einlesen:** Jeder Vorgang schreibt
  `LOG/bestellung_einlesen_<Datum>_<Uhrzeit>.log` (Quelle, Anzahl E-Mails/
  Artikel, neu markierte Titel mit Band, bereits markierte, schon im Bestand
  befindliche Bände) und am Ende einen **eigenen Abschnitt „ARTIKEL OHNE
  PASSENDEN EINTRAG“** mit den nicht zugeordneten Artikeln. Es stehen nur
  Artikelnamen und Bandnummern drin – keine Adresse, Bestellnummer, Preise
  oder E-Mail-Dateinamen. Es bleiben nur die neuesten **10** Dateien liegen
  (`order_log_keep` in der `config.json`, mindestens 1); der Pfad wird im
  Hinweisfenster nach dem Einlesen angezeigt.

### Postfach-Abruf (IMAP)

**Konfigurieren → Postfach (IMAP) …** richtet den Zugang ein – unabhängig
vom Anbieter, es genügt ein IMAP-Server. Vorlagen (GMX, WEB.DE, Gmail,
Yahoo, iCloud, T-Online, IONOS, Posteo, mailbox.org) füllen Server, Port und
Verschlüsselung nur vor; jeder andere Server lässt sich frei eintragen.
Mit **„Verbindung testen“** prüfst du Server, Anmeldung und Ordner.

- **Filter:** Ordner (Standard `INBOX`), „Absender enthält“ (Standard
  `konold`), „Betreff enthält“ (Standard `Bestellung`), Zeitraum (Standard
  90 Tage) und maximale Mailanzahl je Abruf.
- **Abruf:** *Datei → Bestellungen aus Postfach abrufen …* sucht passende
  Mails, zeigt sie zur Auswahl (Datum, Betreff, Artikelzahl) und markiert
  danach wie beim .eml-Import. Mails ohne Artikelliste (z. B.
  Versandmitteilungen) werden übersprungen. Ein erneuter Abruf ist
  ungefährlich: bereits gelieferte Bände werden nicht erneut markiert.
- **Passwort:** steht **nie** in `config.json`. Wahlweise wird es in den
  Windows-Anmeldeinformationen gespeichert (Paket `keyring`), sonst wird es
  beim Abruf abgefragt und nur bis zum Programmende im Arbeitsspeicher
  gehalten. Bei GMX, WEB.DE, Gmail u. ä. muss der IMAP-Zugriff in den
  Kontoeinstellungen erlaubt sein, teils ist ein App-Passwort nötig.
  Anbieter, die nur OAuth2 zulassen (z. B. Outlook.com), funktionieren so
  nicht.
- **Nur lesend:** Der Ordner wird schreibgeschützt geöffnet, die Mails
  werden ohne „gelesen“-Markierung geladen; im Postfach wird nichts
  verändert oder gelöscht. Die Verbindung ist verschlüsselt (SSL/TLS oder
  STARTTLS, mit Zertifikatsprüfung). Wie beim Datei-Import werden die
  Mails nicht gespeichert.

## Bestand als CSV exportieren

Menü **Datei → CSV exportieren …** → Speicherort wählen. Exportiert wird der
aktuelle Stand im Zwischenspeicher (also inkl. noch nicht gespeicherter
Änderungen) mit allen regulären Spalten und sprechenden
Spaltenüberschriften in der ersten Zeile – z.B. zur Weiterverwendung in
Excel oder als Sicherungskopie außerhalb der Datenbank. Getrennt wird mit
**Semikolon** (UTF-8 mit BOM): So öffnet Excel mit deutschen Einstellungen
die Datei per Doppelklick direkt in Spalten, mit Komma landete dort alles in
Spalte A. Das Trennzeichen ist über `csv_delimiter` in der `config.json`
einstellbar. Weder die ISBN (liegt in der separaten `isbn_cache`-Tabelle,
siehe Abschnitt „ISBN-Abgleich“ oben) noch die Bestellt-/Angekommen-
Markierungen oder die Spalte „Rückstand“ (nur live berechnet, nie
gespeichert) sind enthalten.

## Bedienung

- **Menü „Datei“** – bündelt alle Verwaltungsfunktionen (keine eigenen
  Buttons mehr): Neuer Eintrag (Strg+N), Bearbeiten, Löschen (mit
  Rückfrage), CSV importieren / exportieren, Von Google Drive laden
- **Menü „Konfigurieren“** – Farben (Untermenü), Konfiguration sowie die
  Schalter „Nach Bearbeitung zur Zeile springen“ und „Gestoppt: keine
  Berechnung“
- **Bei buchhandel.de suchen** (Datei-Menü, Strg+B oder Rechtsklick auf eine
  Tabellenzeile) – öffnet im Browser die buchhandel.de-Suche für den
  markierten Titel (gedruckte Bücher ab dem aktuellen Erscheinungsjahr,
  nach Erscheinungsdatum sortiert). Unabhängig vom Fallback-Anbieter des
  ISBN-Abgleichs (Standard dort ebenfalls buchhandel.de).
- **Doppelklick auf eine Zeile** (oder Datei → Bearbeiten) – öffnet das Formular
- **Suche** – oberstes Element der rechten Seitenleiste, filtert live über
  alle Spalten
- **Filter – Verlag / VÖ +1** – zwei Dropdowns in der Werkzeugleiste (rechts neben „ISBN-Abgleich“),
  kombinierbar mit der Suche und miteinander. „VÖ +1“ bietet neben „Alle“
  die Status Beendet/TBA/Gestoppt/NA sowie „Mit Datum“ (nur Einträge mit
  einer echten, erkannten Terminangabe). „Filter zurücksetzen“ setzt beide
  Dropdowns und die Suche auf einmal zurück.
- **Titel-Spalte** – passt ihre Breite automatisch an den längsten
  aktuell vorhandenen Titel an (über die gesamte Sammlung, nicht nur die
  gefilterte Ansicht) – keine feste Breite, reagiert live auf neue,
  geänderte oder gelöschte Titel.
- **Klick auf eine Spaltenüberschrift** – sortiert danach (erster Klick
  aufsteigend, erneuter Klick auf dieselbe Spalte kehrt zu absteigend um).
  Ganz rechts steht die Spalte **„Rückstand“** (Bände (bis) − Gelesen bis,
  nicht gespeichert, nur live berechnet) – aufsteigend sortiert (erster
  Klick) stehen die Reihen mit dem kleinsten Leserückstand oben,
  absteigend sortiert (zweiter Klick) die mit dem größten.
- **Ziehen am rechten Rand einer Spaltenüberschrift** – passt die
  Spaltenbreite an (native Qt-Funktion des Tabellenkopfs)
- **↶ Rückgängig / ↷ Wiederholen** (auch Strg+Z / Strg+Umschalt+Z) – macht
  die letzte Änderung (Anlegen, Bearbeiten, Löschen, „+1“, CSV-Import,
  Bestell-Markierungen) rückgängig bzw. wiederholt sie. Bezieht sich nur auf
  den Zwischenspeicher; ein Google-Drive-Download setzt die Rückgängig-
  Historie zurück, da er den Bestand von außen ersetzt. Abgelehnte Aktionen
  (z. B. „+1“ über „Bände (bis)“ hinaus) erzeugen keinen Rückgängig-Schritt.
- **„Nach Bearbeitung zur Zeile springen“** – Schalter im Menü „Konfigurieren“
  (Startwert kommt aus der Konfigurationsdatei, siehe unten). Da eine
  Änderung (z. B. ein „+1“-Klick) den Eintrag durch die Neusortierung an
  eine andere Position verschieben kann, springt die Ansicht dorthin
  automatisch mit. Bei deaktiviertem Schalter bleibt die aktuelle
  Scroll-Position stattdessen unverändert erhalten. Die Einstellung wird
  bei jeder Änderung sofort dauerhaft gespeichert.
- **💾 Speichern** (Strg+S) – schreibt alle gepufferten Änderungen in die Datenbank
- **Konfigurieren → Konfiguration …** – öffnet die zentrale Konfigurationsdatei direkt zum
  Bearbeiten (siehe eigener Abschnitt unten)

Die Felder „Typ“, „Komplett“, „Beendet“ und „Verlag“ sind als Dropdown
vorausgefüllt, lassen sich aber auch frei eintippen.

Beim Übernehmen prüft das Formular die Eingaben und nennt alle Probleme auf
einmal:
- Der Titel ist Pflicht und darf nicht schon vorkommen (Groß-/Kleinschreibung
  egal) – doppelte Titel würden ISBN-Abgleich und Bestellzuordnung
  durcheinanderbringen.
- „Bände (bis)“ und „Gelesen bis“ sind leer oder ganze Zahlen, und „Gelesen
  bis“ ist nicht größer als „Bände (bis)“.
- Datumswerte (Zugang, VÖ) müssen gültig sein (TT.MM.JJJJ oder MM.JJJJ);
  Freitext wie „TBA“ oder „Band 17 11.06.2025“ bleibt erlaubt.

Die VÖ+1-/Komplett-Beendet-Farblegende steht als dauerhafter Bereich am
rechten Rand der Fußzeile/Statusleiste, unabhängig von den normalen
Statusmeldungen (z. B. „Gespeichert“).

## Seitenleiste

Rechts neben der Tabelle steht eine Seitenleiste (standardmäßig 15 % der
Fensterbreite, per Ziehen am Trenner frei verstellbar):

- **Statistik** – Summe im Besitz, Summe gelesen, Differenz und
  Gelesen-Anteil (bisher oberhalb der Tabelle, jetzt hier).
- **Anzahl nach Verlag** – Liste aller aktuell vorkommenden Verlage mit
  ihrer jeweiligen Titel-Anzahl, absteigend sortiert. Passt sich
  automatisch an, sobald ein neuer Verlag auftaucht oder der letzte
  Eintrag eines Verlags verschwindet.
- **Anzahl nach Typ** – je Typ (Manga/Manhwa/Light Novel) die Bände-Bilanz
  als drei Zahlen in der Reihenfolge **Gesamt** (Summe „Bände (bis)“),
  **Gelesen** (Summe „Gelesen bis“) und **Offen** (Gesamt − Gelesen), z. B.
  „Manga: 1207 · 500 · 707“ – die Reihenfolge steht einmalig als Kommentar
  über der Liste. Absteigend nach Gesamt sortiert. Respektiert „Gestoppt:
  keine Berechnung“ (siehe unten), falls aktiv.
- **Erscheinungstermine** – Anzahl der Termine (Treffer über alle
  VÖ-Spalten VÖ +1 … VÖ +3, nicht nur VÖ +1 – ein Titel mit zwei Terminen
  im selben Zeitraum zählt also zweimal) im aktuellen, im nächsten und im
  übernächsten Kalendermonat, als drei Zähler im selben Stil wie die
  Statistik oben.
- **Ausstehende Termine** – Anzahl der Termine, bei denen eine VÖ-Spalte
  einen Termin **vor** dem aktuellen Kalendermonat zeigt (vermutlich
  bereits erschienen, aber „Bände (bis)“ noch nicht per „+1“
  nachgetragen).
- **Live-Log** – siehe nächster Abschnitt.

## Live-Log

Jede Datenänderung (Anlegen, Bearbeiten, Löschen, die „+1“-Buttons,
CSV-Import, Rückgängig/Wiederholen, Speichern) erscheint sofort als
Zeile im Live-Log unten in der Seitenleiste – sitzungsbasiert, d. h. die
Anzeige beginnt bei jedem Programmstart wieder leer.

Zusätzlich wird jede Änderung dauerhaft in `LOG/aenderungen.log`
protokolliert. Einträge, die älter als `log_retention_days` Tage sind
(Standard **182**, also ca. 6 Monate), werden beim nächsten Programmstart
automatisch nach `LOG/aenderungen_archiv.log` verschoben (nicht gelöscht)
– die laufende Datei bleibt dadurch überschaubar, die Historie bleibt
trotzdem vollständig erhalten. Die Anzahl der Tage ist in der
`config.json` über `log_retention_days` einstellbar (wirkt beim nächsten
Programmstart).

## Zentrale Konfiguration

Der Menüpunkt **Konfigurieren → Konfiguration …** (zusammen mit „Nach Bearbeitung
zur Zeile springen“ und der Option „Gestoppt: keine Berechnung“, siehe
unten) öffnet einen
Editor für `config.json` (liegt neben der `.exe` bzw. neben `main.py`).
Der rohe JSON-Inhalt ist direkt bearbeitbar und wirkt für die meisten
Einstellungen sofort, ohne Neustart. Beim Speichern prüft der Editor nicht
nur die JSON-Syntax, sondern auch Typ und Wert der bekannten Einstellungen
(z. B. `true`/`false` statt `"false"` als Text, ganze Zahlen,
`isbn_shop_url_template` mit `{isbn}`) und speichert erst, wenn alles passt.
Enthält u. a.:

| Schlüssel | Bedeutung | Standardwert |
|---|---|---|
| `isbn_shop_name` | Anzeigename des Buchhändlers für gefundene ISBNs | `Konold` |
| `isbn_shop_url_template` | Link-Vorlage, `{isbn}` wird ersetzt | Konold-Shop |
| `isbn_shop_active` | Zuletzt im ISBN-Dialog gewählter Buchhändler (`Konold`/Standard, `Thalia` oder `Amazon`); leer = Standard-Buchhändler | `""` |
| `isbn_fallback_provider` | Suche bei nicht gefundener ISBN: `buchhandel.de` oder `manga-passion` | `buchhandel.de` |
| `follow_selection_after_edit` | Startwert von „Nach Bearbeitung zur Zeile springen“ | `true` |
| `sidebar_width_fraction` | Anteil der Fensterbreite für die Seitenleiste – **wirkt erst beim nächsten Programmstart** (bewusst so: eine bereits von Hand am Trenner verschobene Breite soll nicht ungefragt überschrieben werden) | `0.15` |
| `exclude_gestoppt_from_stats` | Startwert von „Gestoppt: keine Berechnung“ | `false` |
| `isbn_log_keep` | Wie viele ISBN-Abgleich-Logdateien (`LOG/isbn_abgleich_*.log`) liegen bleiben; die ältesten werden gelöscht (mindestens 1) | `10` |
| `order_log_keep` | Wie viele Logdateien von „Bestellung einlesen“ (`LOG/bestellung_einlesen_*.log`) liegen bleiben; die ältesten werden gelöscht (mindestens 1) | `10` |
| `log_retention_days` | Änderungsprotokoll: Einträge älter als so viele Tage wandern ins Archiv | `182` |
| `csv_delimiter` | Trennzeichen des CSV-Exports: `";"` (Excel mit deutschen Einstellungen), `","` oder `"\t"` (Tab) | `";"` |
| `db_backup_keep` | Wie viele Datenbank-Sicherungen (`BACKUP/manga_library_*.db`, vor jedem Speichern und vor einem Google-Drive-Download) liegen bleiben; die ältesten werden gelöscht (mindestens 1) | `20` |
| `colors_enabled` | Farbcodierung je Kategorie (de)aktivieren: `voe1`, `komplett_beendet`, `verlag`, `bestellt`, `angekommen` (jeweils `true`/`false`; auch über *Konfigurieren → Farben* schaltbar). Deaktivierte Kategorien zeigen stattdessen die normale Zebra-Streifung. | alle `true` |

Die Datei lässt sich auch direkt in einem Texteditor bearbeiten (z. B.
wenn das Programm gerade nicht läuft). Geschrieben wird sie sicher (erst eine
temporäre Datei, dann Austausch in einem Schritt). Ist sie beschädigt (kein
gültiges JSON), meldet das Programm das beim Start und verwendet die
Standardwerte; beim nächsten Ändern einer Einstellung wird die beschädigte
Datei als `config.json.defekt` aufbewahrt statt überschrieben.

### Gestoppt: keine Berechnung

Schalter im Menü „Konfigurieren“ (Startwert kommt aus `config.json`,
Änderungen werden sofort dauerhaft gespeichert): Ist sie aktiv, fließen
Titel mit VÖ +1 = „Gestoppt“ nicht in die Statistik-Box (Summe im Besitz
usw.) und nicht in die Gesamt/Gelesen/Offen-Bilanz je Typ in der
Seitenleiste ein. Reine Anzahl-Auflistungen (Anzahl nach Verlag/Typ)
bleiben davon unberührt.

## Google Drive Anbindung einrichten

1. Gehe zur [Google Cloud Console](https://console.cloud.google.com/) und
   erstelle ein neues Projekt (oder nutze ein bestehendes).
2. Unter **APIs & Dienste → Bibliothek** die **Google Drive API**
   aktivieren.
3. Unter **APIs & Dienste → OAuth-Zustimmungsbildschirm** einen Bildschirm
   vom Typ „Extern“ anlegen (für den privaten Gebrauch reicht es, dich
   selbst als Testnutzer einzutragen).
4. Unter **APIs & Dienste → Zugangsdaten → Zugangsdaten erstellen →
   OAuth-Client-ID** den Typ **Desktop-App** wählen.
5. Die heruntergeladene JSON-Datei umbenennen in `credentials.json` und
   neben `main.py` (bzw. neben die spätere `.exe`) legen.

Beim ersten Klick auf „Zu Google Drive sichern“ öffnet sich ein
Browserfenster zur Anmeldung. Danach wird ein Token in `token.json`
gespeichert, sodass du dich nicht erneut anmelden musst. Ist das Token
abgelaufen oder widerrufen, wird automatisch neu angemeldet.

Hoch- und Herunterladen laufen im Hintergrund – die Oberfläche friert
dabei nicht ein, auch nicht, während die Anmeldung auf den Browser wartet.
Wird die Anmeldung nicht innerhalb von 5 Minuten abgeschlossen, bricht der
Vorgang mit einer Meldung ab.

⚠️ **Wichtig:** `credentials.json` und `token.json` sind persönliche
Zugangsdaten – nicht weitergeben.

## Als eigenständige .exe bauen (Windows)

Die Umwandlung in eine `.exe` muss **auf einem Windows-Rechner**
durchgeführt werden (eine Windows-exe lässt sich nicht von Linux/macOS
aus erzeugen). Mitgeliefert ist dafür `build.bat`.

1. Python auf dem Windows-Rechner installieren, falls noch nicht
   vorhanden (bei der Installation „Add python.exe to PATH“ ankreuzen).
2. In diesem Ordner (`mangalib`) per Doppelklick `build.bat` ausführen,
   oder in der Eingabeaufforderung:
   ```powershell
   cd mangalib
   build.bat
   ```
   Beim ersten Mal legt `build.bat` eine eigene Build-Umgebung
   `.venv-build` an (dauert einige Minuten), danach geht es schneller.
3. Nach Abschluss liegt `dist\MangaLibrary.exe` bereit.

**Reproduzierbar und schlank:**
- **Eigene Umgebung, feste Versionen:** Gebaut wird in `.venv-build` mit
  den exakt festgelegten Versionen aus `requirements-build.txt`. Jeder
  Build enthält dieselben Bibliotheken, unabhängig davon, was im globalen
  Python installiert ist. Wie man die Versionen aktualisiert, steht oben in
  `requirements-build.txt`.
- **Eine Bauanleitung:** Was in die exe kommt, steht ausschließlich in
  `MangaLibrary.spec`; `build.bat` ruft nur PyInstaller damit auf.
- **Nur, was das Programm braucht:**
  - von Qt nur QtCore/QtGui/QtWidgets (Paket `PySide6-Essentials`, ohne
    Web-Engine, 3D, Multimedia …)
  - von den über 500 Google-API-Beschreibungen nur die für Google Drive
  - Das hält die exe klein, und sie startet schneller: Eine exe aus einer
    Datei entpackt sich bei jedem Start erst in einen temporären Ordner.
- `build.bat --no-pause` wartet am Ende nicht auf einen Tastendruck – zum
  Aufruf aus eigenen Skripten.
4. `MangaLibrary.exe` in einen eigenen Ordner legen (z.B. Desktop) und
   von dort starten. `manga_library.db`, `credentials.json` und
   `token.json` legen sich automatisch **neben** die exe – die exe also
   nicht isoliert verschieben oder von einem USB-Stick o.ä. starten, ohne
   dass diese Begleitdateien mitkommen, sonst startet sie jedes Mal mit
   einer leeren Datenbank bzw. verlangt erneut die Google-Anmeldung.

`credentials.json` (falls Google-Drive-Sync gewünscht ist) danach manuell
in denselben Ordner wie `MangaLibrary.exe` legen.

Falls die exe beim Start oder bei „Zu Google Drive sichern“ ein fehlendes
Modul meldet: Das Modul in `MangaLibrary.spec` bei `hiddenimports`
ergänzen und neu bauen. Unerwartete Fehler stehen mit allen Details in
`LOG\fehler.log` neben der exe.

## Projektstruktur

```
mangalib/
├── main.py            Startpunkt (startet die Qt-Anwendung)
├── gui/                Grafische Oberfläche (PySide6/Qt), aufgeteilt in:
│   ├── __init__.py       Re-Export (from gui import MangaLibraryApp funktioniert weiterhin)
│   ├── constants.py      Geteilte Konstanten/Hilfsfunktionen (kein Qt-Code)
│   ├── table.py          MangaTableModel, CellDelegate (Tabellen-Darstellung)
│   ├── dialogs.py        EntryDialog, ConfigDialog, IsbnLookupDialog
│   ├── mail_dialogs.py   MailSettingsDialog, MailSelectDialog (Postfach-Abruf)
│   ├── isbn_view.py      IsbnResultWindow (Ergebnis des ISBN-Abgleichs)
│   ├── worker.py         AsyncCall (Hintergrund-Aufgaben mit Qt-Signalen)
│   └── main_window.py    MangaLibraryApp (Hauptfenster)
├── library.py          Zwischenspeicher mit Rückgängig/Wiederholen (ohne Qt, getestet)
├── models.py           Werk-Dataclass (formales Datenmodell, dict-kompatibel)
├── config.py           Zentrale Konfiguration (config.json)
├── changelog.py        Änderungsprotokoll, Log-Dateien, Fehler-Log
├── database.py         SQLite-Zugriff, Schema-Versionen, Sicherungen (BACKUP/)
├── logic.py            "+1"-Aktionen, Markierungen, Formularprüfung
├── colors.py           Farbcodierung (VÖ+1, Komplett/Beendet, Verlag, Zebra)
├── sorting.py          Datums-/zahlenbewusste Sortierschlüssel
├── isbn_lookup.py      ISBN-Abgleich (DNB) & Bestellliste, isbn_cache/isbn_sonderausgaben
├── shops.py            Buchhändler-Links für die Bestellliste
├── paths.py            Basisverzeichnis - funktioniert auch als gebündelte exe
├── drive_sync.py       Google-Drive-Sicherung/-Wiederherstellung
├── import_csv.py       CSV-Einlesen (liefert Daten für den Puffer)
├── csv_export.py       CSV-Export (Semikolon, für Excel)
├── order_mail.py       Bestell-E-Mail (.eml) lesen, Artikel den Einträgen zuordnen
├── mail_fetch.py       IMAP-Abruf von Bestellbestätigungen (anbieterunabhängig)
├── tests/              Automatisierte Tests (pytest)
├── build.bat           Baut die exe (eigene Build-Umgebung, feste Versionen)
├── MangaLibrary.spec   PyInstaller-Bauanleitung: was in die exe kommt
├── requirements.txt    Python-Laufzeit-Abhängigkeiten
├── requirements-build.txt Exakte Versionen für den exe-Build
├── requirements-dev.txt Zusätzlich für Entwicklung: pytest, Ruff (Linter)
├── pyproject.toml      Konfiguration des Linters Ruff
├── .github/workflows/  Automatische Tests auf GitHub (CI)
└── Manga - Besitz.csv  Deine ursprüngliche Liste (nur lokal, nicht im Repo)
```

## Automatisierte Tests

Für alle Module ohne Qt-Oberfläche gibt es eine pytest-Suite unter
`tests/`, u. a.:
- **Zwischenspeicher** (`library.py`): Rückgängig/Wiederholen, ungespeicherte
  Änderungen, Markierungen, CSV-Import
- **„+1“ und Formularprüfung** (`logic.py`)
- **Datenbank:** Migrationen, atomares Speichern, Sicherungen, Austausch der
  Datenbankdatei
- **ISBN-Abgleich:** Bandnummer, Sonderausgaben, Prüfziffer, Suchanfrage –
  mit nachgebauten DNB-Antworten, ohne Netzwerk
- **Bestell-Mails und Postfach-Abruf** (mit nachgebautem IMAP-Server)
- **Weitere:** Konfiguration, CSV-Export/-Import, Google-Drive-Download (mit
  nachgebautem Dienst), Protokolle

```
pip install -r requirements-dev.txt
pytest
```

**Linter (Ruff):** prüft den Quelltext auf echte Fehler (z. B. ungenutzte
Importe, undefinierte Namen), typische Fallstricke, pauschale
`except Exception` ohne Begründung, Import-Reihenfolge und Zeilenlänge (120
Zeichen). Welche Regeln gelten, steht in `pyproject.toml`; bewusst
ausgenommen sind z. B. die deutschen Anführungszeichen „…“ in Texten.

```
python -m ruff check .          # prüfen
python -m ruff check . --fix    # automatisch Behebbares gleich korrigieren
```

Die Ruff-Version ist in `requirements-dev.txt` fest vorgegeben, damit neue
Regeln einer neueren Version nicht unbemerkt Fehler melden – beim Anheben
einmal `ruff check .` laufen lassen.

**Automatisch auf GitHub (CI):** Bei jedem Push auf `main` und bei jedem
Pull Request führt GitHub Actions zuerst Ruff aus und dann die Tests auf
einem frischen Windows-Rechner – mit Python 3.9 (älteste unterstützte
Version) und 3.14 (`.github/workflows/tests.yml`). Das Ergebnis steht im
Pull Request (grüner Haken bzw. rotes Kreuz, Ruff-Funde direkt an der
betroffenen Codezeile) und als Abzeichen oben in dieser README; über den
Reiter „Actions“ lässt sich ein Durchlauf auch von Hand starten.

## Formales Datenmodell (models.py)

`Werk` ist eine dataclass mit allen gespeicherten Feldern
(`database.STORED_COLUMN_NAMES`, also auch den Markierungen `bestellt` und
`angekommen`; dynamisch daraus erzeugt, keine zweite, unabhängig zu
pflegende Feldliste). Sie ist bewusst dict-kompatibel
(`get`/`[...]`/`update`/...), damit sie sich als Drop-in-Ersatz für die
einfachen Dicts verwenden lässt, mit denen der Zwischenspeicher
(`library.py`) arbeitet.

## Hinweis zum Wechsel von Tkinter zu Qt (PySide6)

Die Oberfläche wurde von Tkinter auf Qt (PySide6) umgestellt, um eine
echte virtualisierte Tabellenansicht zu bekommen (nur sichtbare Zeilen
kosten Zeichenzeit, spürbar schnellerer Programmstart bei größeren
Sammlungen). Die gesamte übrige Logik (Datenbank, Farben, Sortierung,
ISBN-Abgleich, Google-Drive-Sync, CSV-Import/-Export) ist unverändert und
komplett unabhängig vom GUI-Toolkit – nur das `gui/`-Paket und `main.py`
wurden dafür neu geschrieben.

