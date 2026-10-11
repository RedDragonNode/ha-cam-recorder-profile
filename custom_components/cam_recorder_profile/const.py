"""Konstanten der Integration Cam Recorder Profile."""
from __future__ import annotations

DOMAIN = "cam_recorder_profile"
LEGACY_DOMAIN = "spielpartner_aufnahme"  # Quelle fuer die einmalige Uebernahme von Cams/Profilen

SUBENTRY_CAM = "cam"
SUBENTRY_PROFILE = "profil"

SIGNAL_LOADED = f"{DOMAIN}_loaded"  # wird nach jedem (Neu-)Laden gesendet, Spielpartner Aufnahme laedt dann nach

# --- Einstellungen (config_entry.options) -------------------------------------
CONF_RECORDER_URL = "recorder_url"
CONF_RECORDER_KEY = "recorder_schluessel"
DEFAULT_RECORDER_URL = "http://local-cam-recorder:8099"
OLD_RECORDER_URL = "http://local-spielpartner-recorder:8099"  # Adresse des frueheren Add-ons
CONF_IMPORT = "uebernehmen"  # nur im Formular

DEFAULT_OPTIONS: dict[str, object] = {CONF_RECORDER_URL: DEFAULT_RECORDER_URL}

# --- Cam (Subentry) ------------------------------------------------------------
CONF_CAM_NAME = "name"
CONF_CAM_KUERZEL = "kuerzel"
CONF_CAM_RECORD = "aufnehmen"  # Recorder: diese Cam aufnehmen
CONF_CAM_STREAM = "stream_entity"  # Recorder: Stream-Quelle ueber eine HA-Kamera
CONF_CAM_RTSP = "rtsp_url"  # Recorder: oder direkte RTSP-Adresse (hat Vorrang)

# --- Aufnahme-Profil (Subentry) -------------------------------------------------
CONF_PROF_NAME = "name"
CONF_PROF_FOLDER = "ordner"  # gespeichert als "Haupt/Unter"
CONF_PROF_MAIN = "hauptordner"  # nur im Formular
CONF_PROF_SUB = "unterordner"  # nur im Formular
CONF_PROF_CAMS = "cams"  # Liste von Cam-Subentry-IDs
CONF_PROF_PATTERN = "dateimuster"
CONF_PROF_TRIGGERS = "ausloeser"  # Liste von Entities (an = aufnehmen)
CONF_PROF_AFTER = "nachlauf_sekunden"
CONF_PROF_MAX = "max_dauer_minuten"
CONF_PROF_FROM = "zeit_von"
CONF_PROF_TO = "zeit_bis"
CONF_PROF_SUN = "sonne"  # "", "tag", "nacht"
DEFAULT_PATTERN = "{cam} %CCYY-%MM-%DD %hh-%mm-%ss"

# Felder, die bei der Uebernahme aus Spielpartner Aufnahme mitkommen (Discord-Felder bleiben dort)
CAM_IMPORT_KEYS = (CONF_CAM_NAME, CONF_CAM_KUERZEL, CONF_CAM_RECORD, CONF_CAM_STREAM, CONF_CAM_RTSP)

SERVICE_PROFILE_START = "profil_starten"
SERVICE_PROFILE_STOP = "profil_stoppen"
SERVICE_IMPORT = "cams_uebernehmen"
