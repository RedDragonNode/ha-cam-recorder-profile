# Recorder und Aufnahme-Profile

Der HA-Server schreibt den RTSP-Stream jeder Kamera **ohne Neukodierung**
(ffmpeg `-c copy`) in eine Datei. Keine GPU, kaum CPU, OBS macht nur noch die Live-Szene.

```
Integration (Steuerung)  ──HTTP──▶  Add-on „Cam Recorder“  ──ffmpeg-copy──▶  Kamera (RTSP)
 Cams, Kürzel, Zähler,              pro Cam ein ffmpeg, Neustart,                      │
 Dateinamen, Discord                Stillstandserkennung, Sidecar                      ▼
                                                                         /media/Aufnahmen/…/Spielen mit …/Saison …/
```

## 1. Speicher (externe Platte)

Bewährte Aufteilung der 4-TB-Platte (SSH auf den Debian-Host, als root via `su -`; Formatieren löscht alles):

| Partition | Label | Einhängepunkt | Zweck |
|---|---|---|---|
| `sdb1` (~3,6 T) | `aufnahmen` | `/var/lib/homeassistant/media/Aufnahmen` | Videos |
| `sdb2` (~5 G) | `backups` | `/var/lib/homeassistant/media/Backups` | HA-Backups (nur die letzten 7 Tage) |

Ordner-Beispiel unter `Aufnahmen`: `Der_Fuchsbau/{Spielen_Spezial,bei_Nacht,bei_Tag,mit_Maschine}` und
`Ueberwachung/{Treppe,Flur,Klingel,Wohnzimmer,Buero}`. In fstab mit **UUID** und `defaults,nofail 0 2` eintragen
(`blkid`), danach `systemctl daemon-reload && mount -a`. Prüfen: `docker exec app_local_cam_recorder df -h /media/Aufnahmen`
muss die große Platte zeigen. Der Mount-Ordner hängt von der HA-Installation ab (`docker inspect <add-on> | grep -A6 '"Destination": "/media"'`).

`nofail` verhindert, dass der Server ohne Platte nicht mehr startet. Ohne eingehängte Platte würde das Add-on auf die
Systemplatte schreiben – `mindest_frei_gb` schützt davor (Start wird verweigert).
Richtwert: 5 Cams ≈ 6 GB pro Stunde (Messung mit Fuchsauge H.264 + 4× Reolink HEVC).

## 2. Add-on

1. Ordner `addon/cam_recorder` auf den Server nach `/addons/cam_recorder` kopieren (Samba-Freigabe `addons`).
2. *Einstellungen → Add-ons → Add-on-Store → ⋮ → Nach Updates suchen* → **Cam Recorder** installieren.
3. Unter *Konfiguration* einen `api_key` setzen (mind. 12 Zeichen), starten.

Optionen siehe `addon/cam_recorder/DOCS.md`. Standard: fragmentiertes MP4 (absturzsicher, auch bei Stromausfall
nur die letzte Sekunde verloren), Audio G.711 → AAC, Neustart nach 20 s ohne Daten.

## 3. Integration

*Konfigurieren* von **Cam Recorder Profile**: Adresse `http://local-cam-recorder:8099` und derselbe `api_key` wie im Add-on.

Pro **Cam** (Untereintrag *Cam hinzufügen*): Name, Kürzel, **entweder** eine HA-Kamera als Stream-Quelle
(HA liefert die RTSP-Adresse) **oder** eine direkte RTSP-Adresse (hat Vorrang). Tipp: den **Hauptstream** (volle Auflösung) nehmen.
Die Cam-IDs gehören dieser Integration; Spielpartner Aufnahme liest die Cams von hier und ergänzt nur seine Discord-Felder.

## Aufnahme-Profile

Ein Profil bestimmt, **wohin** welche Cams aufnehmen und **wann**. Anlegen: *Cam Recorder Profile → Aufnahme-Profil hinzufügen*.

| Feld | Bedeutung |
|---|---|
| Name | z. B. `Treppe`, `bei Nacht` |
| Zielordner | eine Auswahl mit allen Ordnern und Unterordnern vom Recorder (z. B. `Ueberwachung/Treppe`); eigene Namen (auch mit `/`) lassen sich eintippen und werden angelegt |
| Cams | beliebig viele; eine Cam darf in mehreren Profilen stehen |
| Dateiname | `{cam}`, `{kuerzel}`, `{profil}` und Datum/Zeit `%CCYY %MM %DD %hh %mm %ss`; Standard `{cam} %CCYY-%MM-%DD %hh-%mm-%ss` |
| Auslöser | Bewegungsmelder, Schalter, Sensor (mehrere möglich): irgendeiner „an" = aufnehmen |
| Nachlauf | Sekunden, die nach „aus" weiter aufgenommen wird |
| Höchstdauer | Minuten pro Aufnahme (0 = unbegrenzt); danach erst nach „aus → an" wieder |
| Von / bis, Sonne | Zeitfenster (auch über Mitternacht) und/oder nur Tag bzw. Nacht (`sun.sun`) |

Regeln:

- **Nur Zeitfenster/Sonne, kein Auslöser:** nimmt im Fenster durchgehend auf (z. B. „bei Nacht").
- **Auslöser (+ Fenster):** nimmt auf, solange ein Auslöser „an" ist und das Fenster offen ist.
- **Nichts angegeben:** nur von Hand (`profil_starten` / `profil_stoppen`, Name als Parameter).
- **Eine Cam nimmt nie in zwei Profilen gleichzeitig auf:** wer zuerst kommt, belegt sie; das andere Profil
  nimmt ohne diese Cam auf und meldet sie als „belegt". Das gilt auch gegenüber dem Ablauf von Spielpartner Aufnahme (Sitzung `default`).
- Von Hand gestartete Profile laufen bis zum manuellen Stopp. Nach HA-Neustart werden laufende Profile wieder erkannt.
- Pro Profil gibt es einen Binärsensor *Aufnahme* (Ordner, seit, Cams) am Gerät „Profil …".

Beispiel Überwachung Treppe: Ordner `Ueberwachung/Treppe`, Cam Treppe, Auslöser Bewegungsmelder Treppe, Nachlauf 30 s, Höchstdauer 10 min.

## Dateien & Synchronisation

Neben den Videos liegt pro Aufnahme `<Profil> <Datum Zeit>.json` (Start/Ende je Cam und Teil in UTC). Fuer den Schnitt
lassen sich die Kameras damit zeitgenau ausrichten. Ein-/Ausschaltverzoegerungen von wenigen Sekunden zwischen den
Cams sind normal (RTSP-Verbindungsaufbau).

## Entities

Global: *Recorder erreichbar*, *Status*, *freier Speicher*. Pro Cam: *Aufnahme*. Pro Profil: *Aufnahme*.

## Sicherheit

Das Add-on ist nur im internen Home-Assistant-Netz erreichbar (kein veröffentlichter Port) und verlangt den
`api_key`. Zugangsdaten in RTSP-Adressen werden in Logs und Status maskiert. Pfade werden bereinigt;
Ordner außerhalb von `aufnahme_ordner` sind nicht erreichbar.

## Umzug aus Spielpartner Aufnahme 0.4.x

1. Alten Add-on „Spielpartner Recorder“ stoppen, `api_key`/`aufnahme_ordner` notieren, Add-on **Cam Recorder** installieren und starten, altes deinstallieren.
2. Cam Recorder Profile installieren, Home Assistant neu starten, Integration hinzufügen. Beim Einrichten
   *„Cams und Profile aus Spielpartner Aufnahme übernehmen“* anhaken (oder später den Service `cam_recorder_profile.cams_uebernehmen` aufrufen).
   Die IDs bleiben gleich, Profile und Verweise stimmen weiter.
3. Spielpartner Aufnahme 0.5.0 einspielen; bei den Einstellungen die Recorder-Adresse auf `http://local-cam-recorder:8099` ändern.
   Beim ersten Start räumt die Integration die übernommenen Cams und Profile bei sich auf.
