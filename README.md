# NOEMA J.A.R.V.I.S. – Windows Dashboard

[Setup-EXE und komplettes ZIP herunterladen](https://github.com/noema-ai-open/NOEMA-J.A.R.V.I.S.---TikTok-Live-Bridge-NEED/releases/latest)

Das Setup installiert JARVIS mit eigener Python-Laufzeit und Desktop-Verknüpfung. Die NOEMA TikTok Live Bridge auf Port 8765 ist eine separate Anwendung und wird hier nicht mitgeliefert.

# NOEMA J.A.R.V.I.S. Live AI Bridge

Lokaler FastAPI-Dienst für kurze KI-Antworten im TikTok LIVE. Die vorhandene
[`noema-tiktok-live-bridge`](https://github.com/noema-ai-open/noema-tiktok-live-bridge)
bleibt allein verantwortlich für TikTok-Verbindung, Normalisierung, Filter,
WebSocket-Events, TTS-Queue und Audioausgabe.

## MVP-Datenfluss

```text
TikTok Bridge /ws/events
  -> Event- und Frageerkennung
  -> begrenzte, stabile Priority Queue (Gift-Boost)
  -> nativer LM-Studio-v1-Provider oder optionaler OpenAI-kompatibler Cloud-Provider
  -> Streaming-Antwort in der Jarvis UI
  -> fertige Antwort an TikTok Bridge /tts/test
```

Optional kann das Backend ausdrücklich aktuelle Fragen über die Brave Search API
erden. Suchtreffer gelten als nicht vertrauenswürdige externe Daten und werden
nur als Faktenkontext an das lokale Modell übergeben. YouTube-Treffer laufen im
offiziellen YouTube-IFrame-Player. Optional erkennt der interaktive Musikmodus
ausdrückliche Zuschauerwünsche, sucht selbstständig und startet einen Treffer.
Ein neuer gültiger Wunsch ersetzt den laufenden Titel unmittelbar.
Ein globaler Cooldown begrenzt Spam; Stop, Pause und Lautstärke bleiben geschützt.

Unterstützte Eingangsereignisse: `chat_message`, `gift`, `follow`, `share` und
`status`. Alle Chatnachrichten gelangen in die AI Queue; erkannte Fragen werden
dabei weiterhin gekennzeichnet. Ein Gift erhöht die Priorität der ältesten noch
offenen Nachricht desselben Nutzers, ohne Zeitstempel oder ursprüngliche
Event-Reihenfolge umzuschreiben.

Von der TikTok Bridge markierte Simulationsereignisse werden im Live-Dienst
ignoriert. **Queue leeren** entfernt wartende Nachrichten, beendet eine laufende
LLM-Antwort und stoppt die TTS-Wiedergabe.

Der kanonische Qwen-/LM-Studio-Systemprompt liegt in
[`docs/QWEN_JARVIS_SYSTEM_PROMPT.md`](docs/QWEN_JARVIS_SYSTEM_PROMPT.md) und ist
bereits im Backend eingebaut. Er kann unter **Settings → System Prompt** zur
Laufzeit angepasst werden. In LM Studio muss er deshalb nicht zusätzlich als
Preset eingetragen werden.

Gift-Ansprache besitzt im MVP zwei Stufen:

- **Supporter** – jedes Gift, beispielsweise eine Rose: bevorzugte Frage mit
  einer sehr kurzen persönlichen Danksagung beantworten.
- **Spotlight** – Donut/Doughnut: stärkerer Queue-Boost und eine besonders
  persönliche, souveräne Ansprache vor der Antwort.

Ohne offene Frage erzeugt ein Gift keine eigenständige LLM-/TTS-Antwort.
Ein standardmäßig `0,75` Sekunden langes Gift-Fenster lässt unmittelbar nach
einer Frage eintreffende Gifts noch sicher in deren Priorisierung einfließen.
Kommt das Gift zuerst, wird es höchstens 90 Sekunden für die nächste Frage
desselben Nutzers vorgemerkt.

## Windows-Schnellstart

Voraussetzungen:

- Windows 10/11
- Python 3.12 oder neuer
- laufende TikTok Bridge unter `http://127.0.0.1:8765`
- für echte Antworten: laufender OpenAI-kompatibler Server, standardmäßig LM
  Studio unter `http://127.0.0.1:1234/v1`

In PowerShell:

```powershell
Set-Location C:\GitHub\noema-live-ai-bridge
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
python -m app.main
```

Danach `http://127.0.0.1:8770` öffnen. Das Dashboard zeigt auch bei getrennten
externen Diensten den Zustand sauber an. Über **+ Demo Frage**, **+ Demo Rose**
und **+ Demo Donut** kann der Event-/Queue-Pfad ohne WK02 getestet werden.

## Windows-EXE bauen

Die Desktop-Variante öffnet das Dashboard automatisch im Standardbrowser. Eine
fensterlose Einzeldatei kann direkt aus dem Repository gebaut werden:

```powershell
.\scripts\build-exe.ps1
```

Das Ergebnis liegt anschließend unter `dist\NOEMA-JARVIS.exe`. Frontend,
Jarvis-Animation und PNG-Assets werden in die EXE eingebettet. Konfiguration und
Secrets bleiben außerhalb der EXE in der lokalen Laufzeitumgebung.

## VM01/WK02-Aufteilung

Für den aktuellen Zwei-PC-Aufbau gilt:

- **VM01:** LM Studio mit Qwen und der lokale API-Server auf `127.0.0.1:1234`
- **WK02:** TikTok Studio, TikTok Live Bridge, NOEMA Dashboard und TTS/Audio
- **SSH-Reverse-Tunnel:** stellt VM01-Port `1234` auf WK02 ausschließlich als
  `127.0.0.1:1234` bereit; es wird kein LLM- oder Bridge-Port im LAN geöffnet.

Versionskontrollierte Starter liegen unter `scripts/`:

- `start-lm-studio-server-vm01.cmd`
- `start-wk02-tunnel-vm01.cmd`
- `start-noema-wk02.cmd`

Die Starter enthalten keine Passwörter oder API-Schlüssel. Der Tunnel nutzt den
dedizierten Schlüssel `%USERPROFILE%\.ssh\id_wk02_noema_ed25519`.

### Desktop-Startknöpfe

- VM01: `NOEMA 1 - LM Studio und Tunnel`
- WK02: `NOEMA 2 - JARVIS Dashboard`

Die Verknüpfungen lassen sich reproduzierbar aus dem Repository anlegen:

```powershell
# auf VM01
.\scripts\install-desktop-shortcut.ps1 -Role VM01

# auf WK02
.\scripts\install-desktop-shortcut.ps1 -Role WK02
```

Die TikTok Live Bridge bleibt bewusst separat und wird weiterhin mit ihrem
eigenen Starter geöffnet.

## LM Studio einrichten

1. Modell in LM Studio laden.
2. Local Server auf Port `1234` starten.
3. In der NOEMA-Oberfläche unter **Settings** die exakte Model ID eintragen.
4. Endpoint auf `http://127.0.0.1:1234/v1` belassen oder anpassen.
5. Mit **Speichern & LLM testen** Model-ID, Antwort und Latenz ohne TTS prüfen.
6. AI gegebenenfalls mit **AI fortsetzen** entsperren.

TikTok-Standardprofil:

| Einstellung | Standard |
| --- | --- |
| Reasoning/Thinking | aus |
| Streaming | an |
| Context Length | 8192 |
| Max Output Tokens | 120 |
| Temperature | 0.6 |
| Timeout | 20 Sekunden |

Es gibt keinen stillen CPU- oder Modell-Fallback. Bei einem LLM-Fehler bleibt
die Frage erhalten und die AI pausiert fail-closed. Ein konfigurierter Cloud-
Fallback nutzt dieselbe OpenAI-kompatible Provider-Schnittstelle.
Der lokale Provider nutzt `POST /api/v1/chat`, damit `Reasoning aus` von LM
Studio tatsächlich erzwungen wird; Reasoning- und Tool-Events werden nie an UI
oder TTS weitergegeben.

## Bedienung

- **AI pausieren/fortsetzen:** Queue-Verarbeitung kontrollieren
- **Frage skippen:** laufende Generierung abbrechen
- **Queue leeren:** wartende und aktive Verarbeitung beenden und TTS stoppen
- **TTS Stop:** `/tts/stop` der TikTok Bridge aufrufen
- **LOCAL/CLOUD:** aktiven Provider wählen
- **Settings:** Endpoints, Modelle, Limits und Provider konfigurieren
- **Internet & Musik:** Brave-Web-/YouTube-Suche und interaktiver YouTube-Player
- **Spotify Connect:** optional ein privates Spotify-Gerät steuern; NOEMA mischt
  dabei keinen Spotify-Ton in TikTok

API-Schlüssel werden maskiert eingegeben, nie über GET-Endpunkte zurückgegeben
und nicht geloggt. Runtime-Einstellungen werden lokal als ignorierte
`runtime-settings.json` im Projektordner gespeichert und beim nächsten
manuellen Start wieder geladen. Auf ausdrücklichen Wunsch enthält diese lokale,
nicht versionierte Datei auch API-Keys im Klartext. Sie darf nicht geteilt oder
in ein Repository kopiert werden. `.env.example` enthält ausschließlich
Platzhalter; `.env` ist ignoriert. Die Anwendung lädt keine `.env`-Datei
automatisch.

### Internet und YouTube

1. Einen neuen Brave-Search-API-Key erzeugen; niemals einen im Chat oder Repository
   veröffentlichten Schlüssel weiterverwenden.
2. Unter **Settings** `Brave-Suche aktiv` und optional `YouTube aktiv` einschalten.
3. Den Schlüssel in das maskierte Feld **Brave API Key** eintragen und speichern.
4. Über **Internet & Musik** suchen. Nur YouTube-Treffer mit gültiger Video-ID
   erhalten eine Wiedergabe-Schaltfläche.
5. Für Zuschauerwünsche **Interaktive Musikwünsche** aktivieren und einen Cooldown
   festlegen. Nachrichten wie „Spiel bitte Chillout-Musik auf YouTube“ werden dann
   automatisch gesucht und abgespielt. Browser können vorab einen einmaligen
   manuellen Play-Klick verlangen.

Alternativ kann der Schlüssel vor dem Start ausschließlich lokal als
`NOEMA_BRAVE_API_KEY` gesetzt werden. Das Backend verwendet den offiziellen
`X-Subscription-Token`-Header und gibt den Schlüssel weder an den Browser noch an
LM Studio weiter. Für gestreamte Musik bleiben Urheber- und Plattformrechte beim
Betreiber; die Anwendung lädt oder extrahiert keine Audiodateien.

### Spotify Connect privat steuern

Spotify Connect ist optional und verwendet den Authorization-Code-Flow mit
PKCE. Ein Client Secret wird nicht benötigt und nie im Browser gespeichert.

1. Im Spotify Developer Dashboard eine App anlegen. Für Development Mode ist
   ein Spotify-Premium-Konto erforderlich.
2. Exakt diese Redirect URI eintragen:
   `http://127.0.0.1:8770/api/spotify/callback`
3. In NOEMA unter **Settings** Spotify aktivieren, die Client ID eintragen und
   als Musikziel **Spotify Connect** wählen.
4. Speichern und unter **Internet & Musik** auf **Spotify verbinden** klicken.
5. Die Spotify-App auf dem gewünschten Gerät öffnen. Danach funktionieren
   Suche, Albumwiedergabe, Pause, Weiter, Skip und Lautstärke sowie die
   Chatbefehle `/musik`, `/album`, `/pause`, `/weiter`, `/skip`, `/lauter`
   und `/leiser`. Beispiel: `/album Daft Punk Random Access Memories`.

Das Refresh-Token wird wie die anderen lokalen Zugangsdaten in der ignorierten
`runtime-settings.json` gespeichert und über die API nicht ausgegeben. Diese
Integration steuert ausschließlich ein privates Spotify-Connect-Gerät; sie
routet, erfasst oder überträgt kein Spotify-Audio.

## Lokale API

- `GET /health`
- `GET /api/status`, `/api/events`, `/api/queue`, `/api/settings`
- `POST /api/settings`
- `POST /api/diagnostics/llm`
- `POST /api/control/pause`, `/skip`, `/clear`, `/tts-stop`
- `POST /api/control/memory-clear`
- `GET /api/spotify/login`, `/callback`, `/status`
- `POST /api/spotify/control`, `/disconnect`
- `POST /api/mock/event`
- `WS /ws/dashboard`

Die Quell-Bridge wird über `ws://127.0.0.1:8765/ws/events` konsumiert. TTS nutzt
`POST http://127.0.0.1:8765/tts/test`; der Sprachstatus wird über
`GET /tts/state` gelesen.

## Tests

```powershell
python -m pytest -q
```

Abgedeckt sind Frageerkennung, stabile Priority Queue, Gift-Boost, Provider-
Streaming und Timeout, Event-Parsing, Reconnect-Backoff, TTS-Client,
Settings-/Secret-Validierung, Health/UI-API sowie die gemockte Kette von Frage
über Streaming-Antwort bis TTS.

Weitere Laufzeitdetails: [docs/TIKTOK_LOCAL_LLM_RUNTIME.md](docs/TIKTOK_LOCAL_LLM_RUNTIME.md).

## Gesprächsspeicher pro Zuschauer

J.A.R.V.I.S. trennt den Gesprächskontext anhand der stabilen TikTok-User-ID.
Die letzten Turns aktiver Zuschauer liegen in einem begrenzten RAM-Cache. Nach
einer erfolgreichen Antwort wird der öffentliche Dialog zusätzlich asynchron
und atomar unter `data/memory/users/` als UTF-8-Markdown gespeichert. Dateinamen
werden aus einem SHA-256-Hash der User-ID gebildet; Anzeigenamen werden niemals
als Pfad verwendet. Beim ersten erneuten Kontakt wird nur die betreffende Datei
lazy geladen. Andere Zuschauer und technische Tool-Daten gelangen nicht in den
Prompt.

Standardwerte:

- 10 aktuelle Turns pro Prompt
- maximal 200 aktive User-Memories im RAM
- maximal 100 Turns pro persistenter User-Datei
- 30 Tage Aufbewahrung; `0` deaktiviert die automatische Löschung

`data/` ist vollständig von Git ausgeschlossen. Queue-Leeren löscht keine
Memories. Eine bewusste Löschung erfolgt getrennt, beispielsweise:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8770/api/control/memory-clear `
  -ContentType 'application/json' -Body '{"scope":"active"}'
```

Für einen einzelnen Nutzer ist `scope: user` zusammen mit `user_id` möglich;
`scope: all` entfernt RAM-Cache und persistente User-Dateien.

## Cloud Primary und lokaler Fallback

Der vorhandene LOCAL/CLOUD-Schalter bleibt erhalten. Bei aktiviertem
Provider-Fallback wird in beide Richtungen ausgewichen: CLOUD zu LOCAL sowie
LOCAL zu CLOUD. Erst wenn beide Provider fehlschlagen, wird die Frage erneut
eingereiht und J.A.R.V.I.S. pausiert mit Fehlerstatus.

OpenRouter-Beispiel:

```text
Cloud Base URL: https://openrouter.ai/api/v1
Cloud Model: qwen/qwen3.7-flash
Fallback Provider: local
```

Der optionale `HTTP-Referer` und `X-Title` können in Settings gesetzt werden.
API-Keys werden maskiert, nicht an das Frontend zurückgegeben und nicht
protokolliert. Der regelbasierte Chat-Router filtert Noise wie `lol`, einzelne
Emojis und Spam vor dem LLM; Fragen, Follow-ups und Befehle erhalten getrennte
Prioritäten. Spotify-Befehle werden nicht zusätzlich als normaler KI-Chat
verarbeitet.

## MVP-Grenzen

Noch nicht enthalten sind Avatar/3D, Lip-Sync, Speech-to-Speech, RAG,
Langzeitgedächtnis, Multi-Agenten, autonome Websuche, Docker oder Cloud-
Infrastruktur. Satzweises TTS-Streaming ist vorbereitet, TTS erhält im MVP aber
bewusst erst die vollständige finale Antwort.
