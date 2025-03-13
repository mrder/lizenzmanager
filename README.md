# Lizenz- und Update Manager

Dieses Projekt stellt einen Flask-basierten Lizenzverifikations- und Update-Manager bereit, der sich per Docker betreiben lässt.

## Funktionen

- **Lizenzverifikation über API**  
  POST-Anfragen an `/api/verify` mit JSON-Daten (ClientID, Lizenz, Version, optional ClientIP).  
  Beispielantworten enthalten Lizenzstatus, Ablaufdatum und, falls vorhanden, Update-Informationen.

- **Dashboard für Lizenzverwaltung und Update Manager**  
  Geschützt durch einen Login (Username/Password über Umgebungsvariablen konfigurierbar).

- **Update Manager**  
  Updates können hochgeladen, gruppiert nach Tool/Programm angezeigt, heruntergeladen und gelöscht werden.

## Installation via Docker

Dieses Projekt wurde für den Einsatz als Docker-Container vorbereitet. Du kannst es wie folgt bauen und starten:

1. **Repository klonen:**

   ```bash
   git clone https://github.com/mrder/lizenzmanager.git
   cd lizenzmanager

## API Anfragen

**1. Beispielanfrage:**

curl -X POST "https://Domain/api/verify" \
     -H "Content-Type: application/json" \
     -d '{"ClientID": "valid-client-id", "Lizenz": "valid-license-key", "Version": "2.0"}'
	 


**2. Beispielantwort:**

{
  "Lizenzstatus": true,
  "Ablaufdatum": "31.12.2030",
  "Nachricht": null,
  "UpdateAvailable": true,
  "LatestVersion": "2.1",
  "UpdateURL": "https://Domain/uploads/abc123_update.zip"
}

**3. Integration**

import requests

url = "https://Domain/api/verify"
payload = {
    "ClientID": "expired-client-id",
    "Lizenz": "expired-license-key",
    "Version": "1.5"
}
headers = {"Content-Type": "application/json"}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
	
