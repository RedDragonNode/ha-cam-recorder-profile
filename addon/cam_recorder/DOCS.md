# Cam Recorder

Schreibt die RTSP-Streams der Kameras **ohne Neukodierung** (ffmpeg `-c copy`) in Dateien. Gesteuert wird das Add-on
von den Integrationen *Cam Recorder Profile* (Aufnahme-Profile) und *Spielpartner Aufnahme* (Spielpartner-Ablauf) - beide
sprechen dasselbe Add-on an. Das Add-on selbst hat keine Oberflaeche.

## Einrichtung
1. Ordner `addon/cam_recorder` aus dem Repository nach `/addons/cam_recorder` auf dem HA-Server kopieren
   (Samba-Freigabe `addons`).
2. *Einstellungen → Add-ons → Add-on-Store → ⋮ → Nach Updates suchen* → „Cam Recorder" installieren.
3. Unter *Konfiguration* einen **api_key** setzen (mindestens 12 Zeichen, frei waehlbar) und starten.
4. In den Integrationen *Cam Recorder Profile* und *Spielpartner Aufnahme* (je unter *Konfigurieren*) Adresse
   `http://local-cam-recorder:8099` und denselben Schluessel eintragen.

### Umzug vom alten Add-on „Spielpartner Recorder"
Das Add-on heisst seit 0.4.0 `cam_recorder` (vorher `spielpartner_recorder` bis 0.3.0). Es ist technisch ein neues Add-on mit
eigenen Einstellungen: `api_key` und `aufnahme_ordner` aus dem alten Add-on uebernehmen, das alte Add-on **vorher stoppen**
(keine zwei Recorder gleichzeitig in dieselben Ordner) und danach deinstallieren. Die API ist unveraendert.

## Einstellungen
| Option | Bedeutung |
| --- | --- |
| `api_key` | Zugangsschluessel zwischen Integration und Add-on |
| `aufnahme_ordner` | Stammordner (voller Pfad, z. B. `/media/Aufnahmen` auf der externen Platte); darunter legen Profile/Spielpartner ihre Ordner an |
| `container` | `mp4` (fragmentiert, absturzsicher) oder `mkv` |
| `audio` | `aac` (G.711 der Kamera wird nach AAC umgewandelt, minimale Last), `copy`, `none` |
| `stillstand_sekunden` | Wenn so lange keine Daten geschrieben werden, wird die Kamera neu verbunden (neue Datei „… Teil 2") |
| `mindest_frei_gb` | Start wird verweigert / Aufnahme beendet, wenn weniger Platz frei ist |
| `wallclock_zeitstempel` | Nur aktivieren, wenn eine Kamera fehlerhafte Zeitstempel liefert |
| `ffmpeg_loglevel` | `warning` (Standard), bei Problemen `info` oder `verbose`: dann zeigt das Protokoll die genaue ffmpeg-Ausgabe |
| `video_tag` | `hvc1` setzt HEVC in MP4 so, dass Windows/Apple-Player es abspielen. Wirkt nur bei MP4; bei Cams mit H.264 wird der Tag automatisch weggelassen |

## Dateien
Pro Sitzung entsteht neben den Videos eine `<Sitzung>.json` mit Start/Ende jeder Kamera und jedes Teils (UTC) –
damit lassen sich die Kameras spaeter zeitgenau synchronisieren.

## Mehrere Profile gleichzeitig (seit 0.3.0 im Vorgaenger)
`POST /start` nimmt optional `profile` an, `POST /stop` optional `profile` (ohne = alle, deshalb schicken die Integrationen immer ihr Profil mit; der Spielpartner-Ablauf nutzt `default`). Jedes Profil hat eigenen Ordner,
eigene Sidecar-Datei und eigenen Speicherwaechter. Eine Kamera-ID kann nie in zwei Profilen gleichzeitig aufnehmen
(Start wird mit „Kamera nimmt bereits in einem anderen Profil auf" abgelehnt). `GET /status` enthaelt zusaetzlich `profile`.
