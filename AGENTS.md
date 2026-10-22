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
- HTTP-Annahme ist noch nicht implementiert. Ziel: Einladungen unabhängig vom
  DOM lesen, per authentifizierter HTTP-Anfrage annehmen und Mitgliedschaft
  eindeutig prüfen. Zunächst vorhandene Browser-Anmeldungen nutzen; erst danach
  eine browserlose Sitzungsverwaltung untersuchen.
- Tests: `python -m pytest -q`; Browserfixtures benötigen Playwright Chromium
  Headless Shell. Die bestehenden Tests weiterhin ausführen.
