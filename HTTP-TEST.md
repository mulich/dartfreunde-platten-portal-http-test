# HTTP-Test und Übernahme

## Tests

```sh
PLAYWRIGHT_BROWSERS_PATH=/PFAD/ZU/PLAYWRIGHT ../.venv/bin/python -m pytest -q
```

HTTP-Tests verwenden MockTransport, keine echten Zugangsdaten. Sie prüfen
401/Refresh-Rotation, falsche Identität, Absenderfreigaben, laufende Matches,
mehrdeutige Antworten, Weiterleitungen, doppelte Einladungen, Timeout nach
serverseitigem Beitritt, schnelle Matchstarts, Pause während eines Requests
und bestätigte lokale Board-Zuordnung. Browserfixtures bleiben zusätzlich aktiv.

## Anmeldung aus dem produktiven Container übernehmen

Die Migration ist vom Nutzer für Muli/Mulich und Die Rote/dierote freigegeben.
Sie überträgt nur den Refresh-Token, keine Passwörter, Cookies oder ganzen Profile.
Im Quellcontainer wird aus einer temporären Kopie ausschließlich des lokalen
Speichers gelesen; alle Webseitenanfragen werden lokal abgefangen. Der Original-
Browser bleibt geschlossen. Tokenwerte werden nur im Speicher über SSH/stdin
transportiert und niemals im Terminal ausgegeben.

SSH im eigenen Terminal öffnen und Passwort dort eingeben:

```sh
ssh -M -S /private/tmp/dartportal-http-ssh -o ControlPersist=15m root@192.168.178.2
```

Dann auf dem MacBook im Testrepository:

```sh
python3 scripts/migrate_http_sessions.py \
  --ssh root@192.168.178.2 --ssh-control /private/tmp/dartportal-http-ssh \
  --lxc 137 --source-container dartfreunde-portal_portal_1 \
  --pause-source Muli 'Die Rote'
```

Das Skript pausiert nur diese Quellsitzungen. Ziel ist ausschließlich der lokale
`dartportal-http-test-portal-1`; bestehende Zielaccounts werden nicht überschrieben.
Der Testcontainer startet anschließend neu. Annahme bleibt zunächst aus.
Die Migration wurde bereits erfolgreich ausgeführt; nicht erneut ausführen.

## Freigegebener realer Test

Die begrenzten Endpunkte `/api/http/test-lobby` (GET/POST) können eine Testlobby
nur mit den angemeldeten Accounts `mulich` und `dierote` verwenden. POST erstellt
oder vervollständigt die lokal protokollierte Lobby, weist dem Gastgeber ein
freigegebenes Board zu und lädt den anderen Account ein. Es startet kein Spiel.
GET liefert ausschließlich die Teilnehmer- und Board-Zuordnung. Der Endpunkt
`/api/http/peers/{id}` liest nur den gegenseitigen Freundesstatus dieser Accounts.
Keine freie API-Proxy-Funktion und kein Export-Endpunkt für Zugangsdaten.

Ein erster Test mit dierote als Gast war erfolgreich. Der anschließende Test mit
Mulich als Gast war noch nicht erfolgreich: HTTP 403 beziehungsweise fehlende
lokale Zuordnung. Eine vollständige Turnierserie ist weiterhin nicht bestätigt.
Die ursprünglichen Sitzungen im Produktivportal bleiben pausiert.

## Dummy-Gastgeber und Einladungsdiagnose

Die Board-Accounts rot/blau/schwarz dürfen nach Lobby-Erstellung aus der
Spielerliste entfernt werden. Der Lobby-Gastgeber bleibt maßgeblich. Eine fehlende
eigene Spielerzeile verhindert den nativen Beitritt mit Gastgeber nicht mehr.
Wenn andere lokale Spieler eine Scheibe des Gastgebers belegen, muss diese mit
der konfigurierten Board-ID übereinstimmen. Erfolg wird erst nach bestätigter
Mitgliedschaft, passendem hostId und passender boardId gemeldet. Eine bereits
anderweitig angenommene Einladung wird nicht still als lokaler Erfolg behandelt.

Realer Befund: Die Einladung von Blau wurde erkannt, aber der native Aufruf
`players/with-host/{host}` antwortete nach Entfernen des Dummy-Spielers mit 404.
Nur in diesem Fall und nach erneuter Prüfung derselben privaten Gastgeber-Lobby
wird der normale native Beitritt `POST players` verwendet. Es werden weder
fremde Host-Rechte noch ein Board auf Verdacht gesetzt. Das Board-Script ordnet
die angenommenen Spieler anschließend über seinen eigenen Gastgeber-Account zu.
Bis dahin meldet das Portal ausdrücklich eine noch fehlende lokale Zuordnung.
Bestätigte normale Beitritte werden auch weiter geprüft, wenn Autodarts die
Einladungsbenachrichtigung bereits entfernt hat. Ein 403 löst diesen Rückfall
nicht aus. Während der Wiederholungspause bleibt der tatsächliche HTTP-Fehler
sichtbar.

Fehler und Wartezustände einer Einladung stoppen die Verarbeitung der übrigen
Einladungen nicht. `/api/players/{id}/automation-diagnostics` liefert pro Einladung
Absender, Lobby, erwartete/beobachtete Scheibe, Verarbeitungsschritt und bereinigten
Fehlercode. Keine Tokens oder Antworttexte von Autodarts. Alte Absender und
HTTP-Statuscodes werden beim nächsten Scan zurückgesetzt. `/health` enthält
zusätzlich `http_revision`, damit die tatsächlich installierte HTTP-Implementierung
unabhängig von der alten Browser-Automatik erkannt wird.

Referenz: aktuelle native Oberfläche vom 25.10.2026,
`https://play.autodarts.com/assets/join_._lobbyId-Br90uBNN.js` und
`https://play.autodarts.com/assets/lobby._lobbyId-DL3P1Vje.js`.
