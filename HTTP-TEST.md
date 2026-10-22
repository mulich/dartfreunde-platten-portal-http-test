# Testplan: Einladungen per HTTP

## Stand

Die produktive Codebasis ist kopiert. HTTP-Annahme und browserlose
Sitzungsverwaltung sind noch nicht implementiert. Das Produktionsrepository
wird durch Änderungen hier nicht aktualisiert.

## Erste Teststufe

1. Autodarts-Anmeldung weiter über den Browser ermöglichen.
2. Einladungen über die native API lesen statt sichtbare Buttons auszuwerten.
3. Annahme mit der aktuellen Anmeldung des jeweiligen Accounts ausführen.
4. Absenderfreigabe, eigene Account-ID, Ziel-Lobby und vorhandene Mitgliedschaft
   vor der Annahme prüfen; nach dem Request die Mitgliedschaft bestätigen.
5. Zuerst Mock-Tests für 401, abgelaufene Einladungen, doppelte Ereignisse,
   falsche Accounts, laufende Matches und unklare Antworten durchführen.
6. Danach einen vom Nutzer ausdrücklich freigegebenen Test mit einem Account
   und einer Lobby durchführen; keine laufenden Turniere verwenden.

Der native Client verwendet `addPlayer` mit `name`, `userId` und aufgelöster
`boardId`. Authentifizierung, Board-Zuordnung und Event-Empfang müssen vor einem
echten Schreibrequest vollständig geprüft werden. Keine gespeicherten Tokens
oder manuell geratenen Account-IDs einbauen.

## Zweite Teststufe

Erst nach erfolgreicher HTTP-Annahme untersuchen, wie Token-Erneuerung und
Event-Verbindung ohne dauerhaft laufenden Chromium-Prozess möglich sind.
CPU- und Speicherverbrauch unter identischen Bedingungen messen; noch keine
Ressourcenersparnis behaupten.
