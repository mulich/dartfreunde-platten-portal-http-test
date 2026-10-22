# Dartportal HTTP-Test

Private Testvariante von `mulich/dartfreunde-platten-portal`.
Änderungen hier aktualisieren das Produktionsportal nicht.

## Lokal auf dem MacBook

```sh
docker compose -p dartportal-http-test up -d --build
```

Öffnen: **http://localhost:18082**. Bindung nur an 127.0.0.1.
Eigene Daten unter `./data-http-test`; keine Produktionsvolumes einbinden.

## HTTP-Sitzungen

- Browser nur zur erstmaligen Anmeldung. Nach bestätigter Übernahme schließt er.
- Token-Erneuerung direkt über `/auth/v1/refresh`, ohne gespeichertes Passwort.
- WebSocket mit kurzlebigem Ticket hält die native Autodarts-Verbindung offen.
- Einladungen kommen über den Broker; die kanonische Liste wird per HTTP gelesen.
- Annahme über den nativen Beitritt mit Gastgeber. Damit werden Host und Board
  direkt lokal zugeordnet, ohne Globus-/Haus-Schaltflächen zu bedienen.
- Erfolg erst bei bestätigter Mitgliedschaft, `isPending=false`, richtigem
  `hostId` und `boardId`; Freundschaftsanfragen werden ignoriert.
- Pause beendet auch die HTTP-/WebSocket-Sitzung. Der Refresh-Token bleibt lokal.

Unter „Test-Gastgeber und Board“ kann für eine separate Lobby ein anderer
Gastgeber als rot/blau/schwarz zugeordnet werden. Die echte Lobby muss dasselbe
Board verwenden. Es wird kein Board-Manager verändert und kein Match gestartet.

## Bereits echt geprüft

Auf dem MacBook mit Docker: Anmeldungen von Mulich und dierote aus pausierten
Produktionsprofilen übernommen; beide sehen einander als Online. Mulich hat
eine private Testlobby auf Blau erstellt. Dierote hat sie automatisch per HTTP
angenommen; beide Spieler haben dasselbe lokale Board und denselben Gastgeber.
Dabei läuft kein Chromium- oder Playwright-Prozess im Container.

Noch keine vollständige Turnierserie, kein Treffer-/Korrekturtest und kein
Langzeitnachweis über mehrere Tage. Automatik für andere Accounts erst in
separaten Testlobbys freigeben.

## Aktuelle Schnittstellen

Die am 22.10.2026 geladene aktuelle Oberfläche `play.autodarts.com` verwendet
`auth/v1` für Login/Refresh, `gs/v0` für Lobbys, `as/v0` für Benachrichtigungen,
`us/v0` für Match-Zuordnung und den Message-Broker `play.ws.autodarts.com/ms/v0`.
Ein `v0` im Pfad ist deshalb kein Beleg für das alte abgeschaltete Frontend.
Es werden keine alten Login-/Keycloak-Endpunkte genutzt. Eine beobachtete 301-
Weiterleitung von `/as/v0/friends` ergänzt lediglich den Schrägstrich.
Nur Weiterleitungen auf denselben HTTPS-Host werden verarbeitet.

## Schutz der Anmeldungen

Refresh-Tokens liegen ausschließlich im separaten Datenvolume unter
`http-sessions/` (Verzeichnis 0700, Dateien 0600). Access-Tokens bleiben im RAM.
Keine Tokens in API-Antworten, Logs, Git, Shellargumenten oder Screenshots.
Dateirechte ersetzen keine Verschlüsselung des Docker-Hosts.

Anmeldungen nicht gleichzeitig in Produktion und Test erneuern: Rotierende
Refresh-Tokens können die andere Instanz abmelden. Nach Migration bleiben die
betroffenen Quellsitzungen pausiert. Zur Rückkehr dort gegebenenfalls neu anmelden.

Details: [HTTP-TEST.md](HTTP-TEST.md), [DEPLOYMENT.md](DEPLOYMENT.md).
