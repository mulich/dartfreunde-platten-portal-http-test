# Dartportal HTTP-Test

Dieses Repository ist die isolierte Testkopie von
`mulich/dartfreunde-platten-portal`, Ausgangsstand
`f70ce6720bca32b50d6e85809b49aa04b75f62a3`.

- Änderungen nur in diesem Testrepository veröffentlichen. Keine Änderungen am
  produktiven Portal oder Turnierplaner ohne ausdrückliche neue Anweisung.
- Container-Port 18082 und eigenes Volume
  `dartfreunde-platten-portal-http-test-data` verwenden. Niemals Profile oder
  Datenvolumes des Produktivportals einbinden oder kopieren.
- Keine echten Lobby-Beitritte oder anderen Spieländerungen ohne Freigabe des
  konkreten Tests durch den Nutzer. Mock-HTTP-Tests zuerst ausführen.
- Keine Zugangsdaten, Browserprofile, Tokens oder Spielerhistorie committen.
- HTTP-Sitzungen in app/http_sessions.py verwenden. Browser nur zur einmaligen
  Anmeldung öffnen und nach erfolgreicher Übernahme schließen. Keine Tokens in
  Diagnose, API-Antworten, Logs, Git oder Befehlsargumente ausgeben.
- Der Nutzer hat die Migration bestehender Anmeldungen freigegeben. Nur ausgewählte,
  pausierte Quellsitzungen übernehmen; die Produktion darf dieselben Refresh-Tokens
  danach nicht parallel erneuern. Migration über scripts/migrate_http_sessions.py.
- Freigegebene Testaccounts: Mulich und dierote; kein Turnier läuft. Andere
  Accounts oder echte Turniere nicht verändern. Scheibe für diesen Test frei wählbar.
- Tests: `python -m pytest -q`; Browserfixtures benötigen Playwright Chromium
  Headless Shell. Die bestehenden Tests weiterhin ausführen.
