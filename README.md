# Dartportal HTTP-Test

Private, eigenständige Testkopie von
[dartfreunde-platten-portal](https://github.com/mulich/dartfreunde-platten-portal),
Ausgangsstand `f70ce6720bca32b50d6e85809b49aa04b75f62a3`.

**Status: isolierte Ausgangsbasis. Die HTTP-Einladungsannahme ist noch nicht
implementiert; aktuell arbeitet hier derselbe UI-Mechanismus wie im Original.**

Die nächsten Schritte und die getrennte Bereitstellung stehen in
[HTTP-TEST.md](HTTP-TEST.md). Für dieses Repository gelten ausschließlich die
Test-Anweisungen in [DEPLOYMENT.md](DEPLOYMENT.md).

## Bisheriger Funktionsumfang der kopierten Account-Zentrale

Ein lokales Portal für mehrere getrennte Autodarts-Accounts in einem Fenster.
Jeder Spieler bekommt ein eigenes Chromium-Profil auf dem Server. Das Portal
überträgt dessen Bildschirm und leitet Klicks, Tastatureingaben und Scrollen weiter.
Es ist keine Einbettung per iframe: So bleiben Cookies und Logins wirklich getrennt.

## Start auf Proxmox / Docker

Docker in einer Linux-VM auf Proxmox verwenden. Im Projektordner:

```sh
docker compose up -d --build
```

Portal unter `http://SERVER-IP:18080` direkt öffnen. Es gibt keine Portal-Passwortabfrage.
Spieler hinzufügen und in der eingebetteten Ansicht bei Autodarts anmelden.
Danach den nächsten Spieler auswählen. Die bisherigen Browser bleiben geöffnet.
Einladungen werden zunächst manuell in den Spieleransichten angenommen.

Für GitHub-Builds, fertige Container-Images und Updates mit Portainer siehe
[DEPLOYMENT.md](DEPLOYMENT.md).

## Turnierteilnehmer und Pause

Nach einem abgeschlossenen Spiel kehren Accounts mit aktivierter Automatik von
der Autodarts-Ergebnisansicht (`/history/matches/…`) zur Startseite zurück.
Die Ergebnisansicht hat keinen Benachrichtigungsbutton. Auf der Startseite kann
das Portal die nächste Einladung wieder öffnen. Laufende Matches und Lobbys
werden dabei nicht verlassen; unbekannte oder abgemeldete Accounts bleiben stehen.

Die Einladungsannahme wartet beim Laden auf den tatsächlichen
Benachrichtigungsbutton. Später eintreffende ungelesene Einladungen öffnen die
native Benachrichtigungsliste auch auf derselben Seite erneut (mindestens
15 Sekunden Abstand). Eine bereits offene Liste wird nicht zugeschaltet oder
geschlossen; Freundschaftsanfragen werden weiterhin nicht automatisch angenommen.

Für die Fehlersuche liefert `/health` den Fingerabdruck des geladenen
Einladungscodes (`invitation_revision`). Unter
`/api/players/{id}/automation-diagnostics` lassen sich der aktuelle Scan,
sichtbare Button-Beschriftungen, die Erkennung des angemeldeten Accounts und die
bisherigen Annahmeversuche rein lesend prüfen. Die Diagnose nimmt keine Einladung
an und gibt keine Zugangsdaten, Cookies, Browser-Speicher oder Eingabefelder aus.

Beim Erstellen eines Turniers fordert der Turnierplaner die bestehenden
Account-Sitzungen der Teilnehmer im Portal an und schaltet deren Einladungsannahme
für die freigegebenen Board-Accounts ein. Er sucht zuerst nach dem exakten
Autodarts-Accountnamen (Groß-/Kleinschreibung egal), danach nach dem Spielernamen.
Mehrdeutige Namen werden nicht automatisch ausgewählt. Fehlende Sitzungen zuerst
im Portal anlegen und einmal bei Autodarts anmelden. Abgelaufene Anmeldungen
müssen erneut bestätigt werden; der automatische Start ersetzt keinen Login.

**Alle pausieren** oben rechts schließt alle Portal-Browser. Die Anmeldungen und
Profile bleiben gespeichert. Die Pause überlebt einen Container-Neustart;
einzelne Sitzungen lassen sich durch Auswahl wieder öffnen. Bereits bestätigte
Aktivierungsanfragen desselben Turniers heben diese Pause nicht auf. Ein neues
Turnier kann seine Teilnehmer wieder starten. Die Pause beendet kein Spiel an
einer physischen Scheibe.

Der Planer verwendet `DARTPORTAL_URL`, im bestehenden Netz standardmäßig
`http://192.168.178.137:18080`. Die Adresse muss vom Turnier-Container erreichbar
sein. Beide Container aktualisieren; zusätzliche Board-Script-Updates sind für
diese Funktion nicht erforderlich.

Für die automatische lokale Zuordnung eingeladener Spieler am Board gibt es ein
[Tampermonkey-Skript für die neue Lobby](LOCAL-PLAYERS.md). Es wird auf den
Board-PCs installiert und ergänzt die Einladungsannahme im Docker-Portal.

## Anmeldung

Unterstützt wird die direkte Anmeldung mit Autodarts-Zugangsdaten in der
Spieleransicht. Google-Anmeldung, separate Chrome-Fenster und QR-Anmeldung
werden nicht unterstützt. Der Betrieb erfolgt über Docker bzw. Portainer;
auf dem Server ist kein Desktop erforderlich.

Bestehende Chromium-Spielersitzungen bleiben im Datenvolume erhalten. Falls ein
Spielerprofil aus der früheren Desktop-/Chrome-Variante stammt, wird daneben ein
neues Chromium-Profil angelegt. Dieser Spieler muss sich mit Autodarts-Zugangsdaten
neu anmelden; das alte Profil wird beim Update nicht gelöscht.

„Sitzung aktiv“ bedeutet Browser aktiv, nicht nachgewiesener Autodarts-Online-Status.
Die App deaktiviert Chromium-Hintergrunddrosselung; ob Autodarts die Accounts über
einen ganzen Abend als online führt, muss mit echten Accounts geprüft werden.
Der Server darf dabei nicht in den Standby gehen.

## Was gespeichert wird

`data/` enthält Spielernamen und die Browserprofile
mit Autodarts-Cookies. Beim Serverstart werden alle gespeicherten Spieler geöffnet.
Eine pausierte Sitzung wird beim nächsten Serverstart ebenfalls geöffnet.
„Entfernen“ löscht Profil und gespeicherte Anmeldung dauerhaft. Autodarts kann
Anmeldungen jederzeit selbst ablaufen lassen und erneute Anmeldung verlangen.
Das Portal hat kein Formular zum Sammeln von Autodarts-Passwörtern. Eingaben in
die Autodarts-Ansicht laufen allerdings durch den Portalserver; dessen Betreiber
muss vertrauenswürdig sein. Das Portal ist für euer eigenes VLAN eingerichtet und
benötigt keine Portal-Anmeldung. Die gespeicherten Autodarts-Anmeldungen bleiben erhalten.

## Lokaler Start ohne Docker

Python 3.11 oder neuer:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PLAYWRIGHT_BROWSERS_PATH="$PWD/data/browsers" .venv/bin/playwright install chromium
PLAYWRIGHT_BROWSERS_PATH="$PWD/data/browsers" .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Docker enthält bereits den passenden Browser.

## Umfang und Grenzen

- Eigene Sitzung je Spieler, Anmeldung und manuelle Einladungsannahme in einem Tab.
- Wechseln, pausieren, erneut öffnen, löschen und Wiederherstellen nach Serverstart.
- Tastatureingabe und Einfügen aus der Zwischenablage; mobile Texteingabe unter der Ansicht.
- Automatische Einladungsannahme pro Spieler; kein Turnierplaner in dieser Version.
- Eine Autodarts-Anmeldung ist nicht gleichzeitiges Spielen an mehreren Boards.
  Jeder Spieler sollte nur seiner aktuellen Begegnung beitreten.
- Zuordnung zum Gastgeber-Board und persönliche Statistik müssen mit echten Matches
  geprüft werden. Das Portal verändert weder Lobbydaten noch Boardauswahl.
- Passkeys, Hardware-Sicherheitsschlüssel, Downloads und Datei-Uploads sind durch
  die Bildschirmfernsteuerung nicht unterstützt. Passwortbasierte Anmeldung und
  per Tastatur eingegebene Bestätigungscodes sind vorgesehen.
- Keine Profilbilder oder Online-Anzeigen erfunden: Das Portal kennt nur den
  Browserzustand; die echten Informationen stehen in der Autodarts-Ansicht.

Pro Account läuft ein eigener Browserprozess. Für den ersten Test mit zwei Spielern
beginnen und RAM/CPU beobachten, anschließend weitere Accounts hinzufügen.
Mehrere Portalnutzer können dieselbe Sitzung bedienen; für Turniere einen Bediener
verwenden. Die Automatik nimmt ausschließlich Einladungen der freigegebenen Board-Accounts an.

## Tests

```sh
.venv/bin/pip install pytest httpx
PLAYWRIGHT_BROWSERS_PATH="$PWD/data/browsers" .venv/bin/python -m pytest -q
```

Die automatischen Tests prüfen direkten Portalzugriff, getrennte Profilverzeichnisse,
Persistenz und Bildschirmsteuerung mit einem simulierten Browser. Sie ersetzen
keinen Login-/Lobby-Test bei Autodarts.

## Automatische Einladungsannahme

Unter „Erlaubte Board-Accounts“ stehen zunächst `rot`, `schwarz` und `blau`.
Die Schreibweise muss dem tatsächlichen Autodarts-Absender entsprechen; Groß- und
Kleinschreibung wird ignoriert. Alternativ können dort eindeutige User-IDs stehen.
Spieler auswählen und „Lobby-Einladungen automatisch annehmen“ einschalten.
Die Einstellung bleibt nach Neustarts erhalten. Anfangs ist sie aus.

Der Server prüft alle Spieler alle zwei Sekunden, unabhängig davon, welche Ansicht
im Portal ausgewählt ist. Er liest die Notification-Daten der aktuellen Autodarts-
Oberfläche und klickt deren normalen Accept-/Join-Knopf. Freundesanfragen und
Turniereinladungen werden nicht angenommen. Ohne erlaubte Absender wird nichts
angenommen. Ein bestätigter Wechsel in die Ziellobby wird mit Uhrzeit angezeigt.
Fehlgeschlagene Beitritte werden höchstens dreimal versucht, mit mindestens 30 Sekunden
Abstand. Aus- und Einschalten erlaubt einen erneuten Versuch.

In einer Lobby oder einem noch laufenden Match wartet die Automatik. Im Match muss
Autodarts den Abschluss im Spielzustand melden; ein unbekannter Zustand blockiert
die Annahme. Zum Wechsel aus einer verlassenen Lobby ggf. „Autodarts öffnen“ drücken.
Beim Aktivieren öffnet die Automatik bei Bedarf einmal den Notification-Bereich,
um noch ungelesene Einladungen zu finden. Die browserinterne React-Datenstruktur
ist keine garantierte öffentliche Schnittstelle und kann sich bei Autodarts-Updates
ändern. Dann bleibt die manuelle Annahme möglich.

Validiert mit Tests und Browserfixtures anhand der öffentlichen Autodarts-Webversion
vom 03.10.2026. Ein echter Eingang einer Einladung von euren Board-Accounts muss
anschließend vor Ort geprüft werden. Das Portal startet keine Spiele automatisch.

## Turnier-Board-Scripts

Im Portal sind separate Tampermonkey-Scripts für Blau, Rot und Schwarz verfügbar.
Sie verbinden die Board-PCs mit https://turnier.mulich.de/ und verwenden die
angemeldeten Portal-Spieler für die Einladungsannahme. Einrichtung, feste Board-IDs,
Spielregeln und Fehlerbehebung: [TURNIER-BOARDS.md](TURNIER-BOARDS.md).
Die Scheiben-Scripts werden im Browser auf den PCs installiert; das Portal selbst
startet weiterhin keine Spiele.
