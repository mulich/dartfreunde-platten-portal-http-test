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

Der erfolgreiche Test läuft auf Board Blau. Die Testlobby bleibt zur Inspektion
bestehen. Die ursprünglichen Sitzungen im Produktivportal bleiben pausiert.
