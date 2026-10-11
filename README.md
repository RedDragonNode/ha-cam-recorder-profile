# Cam Recorder Profile

Private Home-Assistant-Integration plus Add-on: **Kameras direkt vom RTSP-Stream aufnehmen** (ffmpeg Stream-Copy, keine
Neukodierung) – gesteuert über **Aufnahme-Profile** (Zielordner, Cams, Dateiname, Auslöser, Nachlauf, Zeitfenster, Tag/Nacht).

Die Cams (Name, Kürzel, Stream) werden hier verwaltet. Die Integration *Spielpartner Aufnahme* ab 0.5.0 liest sie von hier
und nutzt dasselbe Add-on für ihren Spielpartner-Ablauf.

> Privates Repo, MIT-Lizenz.

## Bausteine

| Baustein | Aufgabe |
|---|---|
| Integration `cam_recorder_profile` | Cams, Aufnahme-Profile, Auslöser, Steuerung |
| Add-on `addon/cam_recorder` | schreibt die Streams per ffmpeg auf die Platte, überwacht und startet bei Abbruch neu |

## Installation

1. **Add-on:** `addon/cam_recorder` nach `/addons/cam_recorder` kopieren, installieren, `api_key` setzen, starten (siehe [DOCS](addon/cam_recorder/DOCS.md)).
2. **Integration:** Ordner `cam_recorder_profile` nach `config/custom_components/`, Home Assistant neu starten,
   *Integration hinzufügen → „Cam Recorder Profile“*, Adresse `http://local-cam-recorder:8099` und Schlüssel eintragen.
3. Cams und Profile als Untereinträge anlegen. Von *Spielpartner Aufnahme 0.4.x*: Übernahme-Haken beim Einrichten (siehe [docs/recorder.md](docs/recorder.md)).

## Services

| Service | Zweck |
|---|---|
| `cam_recorder_profile.profil_starten` | Profil von Hand starten (läuft bis zum Stopp) |
| `cam_recorder_profile.profil_stoppen` | Profil beenden |
| `cam_recorder_profile.cams_uebernehmen` | Cams und Profile aus Spielpartner Aufnahme 0.4.x übernehmen (gleiche IDs) |

## Tests

```bash
pip install -r requirements_test.txt
pytest
```

Mehr: [Recorder, Profile, Umzug](docs/recorder.md)
