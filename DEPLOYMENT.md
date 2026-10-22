# Getrennte Testinstanz

Dieses private Repository ist die Testkopie für die geplante HTTP-Annahme.
HTTP-Sitzungen und Einladungsannahme sind implementiert; siehe README und HTTP-TEST.md. Das Produktivportal bleibt
unter Port 18080 und verwendet sein bisheriges Datenvolume.

## Lokaler Build auf dem Docker-Server

Dieses Testrepository separat klonen und in seinem eigenen Verzeichnis starten:

```sh
docker compose -p dartportal-http-test up -d --build
```

Die Testinstanz läuft auf Port **18082** und verwendet ausschließlich
`./data-http-test`. Keine vorhandenen Spielerprofile hineinkopieren.

## Portainer / fertiges Testimage

Nach erfolgreicher Veröffentlichung durch GitHub Actions:

```text
ghcr.io/mulich/dartfreunde-platten-portal-http-test:latest
```

Einen neuen Stack `dartportal-http-test` anlegen und als Compose-Datei
`compose.portainer.yaml` aus diesem Testrepository verwenden. Es wird ein
neues Volume `dartfreunde-platten-portal-http-test-data` angelegt. Den vorhandenen
Produktivstack nicht bearbeiten oder ersetzen.

Das neue Image kann zunächst privat sein. Falls Portainer keine Berechtigung
zum Laden hat, einen vorhandenen GHCR-Zugang mit Paket-Leserechten verwenden
oder die Variante mit lokalem Build wählen. Ein erfolgreicher Quellcode-Push
belegt noch keine abgeschlossene Image-Veröffentlichung.

Für Updates ausschließlich diesen Teststack mit Re-pull image aktualisieren.
Das Image des Produktivportals gehört nicht in diesen Stack.

## Konten und echte Beitritte

Anmeldungen und Sessions nicht gleichzeitig aus der Produktivinstanz übernehmen.
Erste Tests mit Mock-HTTP durchführen; danach einen einzelnen Account und eine
Testlobby gemeinsam mit dem Nutzer freigeben. Keine laufenden Turniere ändern.
