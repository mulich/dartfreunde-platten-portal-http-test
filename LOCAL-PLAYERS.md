# Spieler automatisch auf das Gastgeber-Board umstellen

Für die neue Autodarts-Lobby gibt es das Userscript
`app/static/autodarts-local-players.user.js`. Es läuft auf den **drei Board-PCs**
im jeweiligen Autodarts-Browser, zusätzlich zum Docker-Spielerportal.

## Installation

1. Den alten **Team Lobby Mode** in Tools for Autodarts ausschalten, damit beide
   Automatiken nicht miteinander arbeiten. Die übrigen Tools können eingeschaltet bleiben.
2. Tampermonkey im Browser des Board-PCs installieren bzw. öffnen.
3. Das Portal auf die neue Docker-Version aktualisieren.
4. `http://SERVER-IP:18080/static/autodarts-local-players.user.js` öffnen und das
   Skript in Tampermonkey installieren. Falls der Browser nur den Quellcode zeigt:
   den gesamten Inhalt in Tampermonkey unter „Neues Skript“ einfügen und speichern.
5. Autodarts neu laden. Eine private Lobby mit dem jeweiligen Board-Account öffnen
   und die gewünschte Scheibe als Scoring-Board auswählen.
6. Links unten erscheint **Spieler lokal: AN**. Unter **Board-Accounts** ggf. die
   tatsächlichen Gastgeber-Namen oder eindeutigen User-IDs eintragen.
   Standardmäßig erlaubt: `rot`, `schwarz`, `blau` (Groß-/Kleinschreibung egal).
7. Zwei echte Spieler einladen. Nach dem Beitritt muss deren Globus zum Haus werden
   und Autodarts die Zuordnung zum Gastgeber anzeigen. Erst danach das Spiel starten.
8. Auf den anderen beiden Board-PCs ebenso einrichten.

Tampermonkey muss das Skript für die Autodarts-Seite ausführen dürfen. Manche
Chromium-Versionen verlangen dafür zusätzlich „Nutzerskripte zulassen“ bzw. den
Entwicklermodus bei den Browser-Erweiterungen; die Tampermonkey-Hinweise beachten.

## Verhalten

Das Skript drückt ausschließlich die native **Globus-Schaltfläche** bestätigter,
eingeladener Spieler in einer privaten Lobby, deren angemeldeter Benutzer als
Gastgeber erkannt wird. Spieler und deren Accounts bleiben in der Lobby erhalten.
Es entfernt den Gastgeber nicht, startet kein Spiel und klickt nie auf ein Haus.
Bereits lokale Spieler, Bots und noch offene Einladungen werden übersprungen.
Lobbys mit Turnierzuordnung und nicht freigegebene Gastgeber werden übersprungen.

Die Erkennung liest die aktuellen React-Props der Spieler-Karte und des
Gastgeber-Startknopfs sowie das `globe`-SVG-Symbol. Es werden weder Zugangsdaten
gelesen noch eigene API-Aufrufe für Änderungen durchgeführt. Der native Klick
verwendet dieselbe Board-Auswahl und Berechtigung wie ein manueller Klick.
Falls Autodarts einen Board-Auswahldialog öffnet, muss die Scheibe dort gewählt werden.

Es wird jeweils nur ein Spieler umgestellt, danach der aktualisierte Zustand
abgewartet. Ohne Bestätigung maximal drei Versuche je Spieler/Lobby mit 15 Sekunden
Abstand. **AUS/AN** setzt die Versuche zurück. Einstellungen bleiben im Browser
gespeichert. Der Schalter ist ausschließlich in der Lobby sichtbar.

## Grenzen und Updates

Validiert anhand des öffentlich ausgelieferten neuen Autodarts-Frontends vom
03.10.2026 und mit isolierten Chromium-Browserfixtures. Ein echter Lobby-Beitritt
und die Zuordnung zu euren Boards müssen vor Ort getestet werden.
Die React-Struktur ist keine zugesicherte Schnittstelle. Wenn sie nicht erkannt
wird, erfolgt kein Klick; die manuelle Globus-/Haus-Umschaltung bleibt verfügbar.

Ein Docker-Update aktualisiert die zum Download bereitgestellte Datei. Ein bereits
in Tampermonkey installiertes Skript muss separat neu installiert/ersetzt werden.
Das Docker-Portal nimmt wie bisher Einladungen für die Spieler entgegen; es steuert
die Gastgeber-Browser auf euren Board-PCs nicht.
