"""Einmalige Uebernahme von Cams und Profilen aus Spielpartner Aufnahme (bis 0.4.x).

Die Subentry-IDs bleiben dabei gleich. Das ist wichtig: sie sind die Cam-IDs im Recorder-Add-on und werden von den
Profilen und von Spielpartner Aufnahme als Verweis benutzt - es muss also nichts umgeschluesselt werden.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant

from .const import (
    CAM_IMPORT_KEYS,
    CONF_RECORDER_KEY,
    CONF_RECORDER_URL,
    DEFAULT_RECORDER_URL,
    DOMAIN,
    LEGACY_DOMAIN,
    OLD_RECORDER_URL,
    SUBENTRY_CAM,
    SUBENTRY_PROFILE,
)


def _legacy_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return hass.config_entries.async_entries(LEGACY_DOMAIN)


def legacy_subentries(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Cams und Profile aus Spielpartner Aufnahme als Subentry-Daten fuer diese Integration."""
    out: list[dict[str, Any]] = []
    for entry in _legacy_entries(hass):
        for sid, sub in entry.subentries.items():
            if sub.subentry_type == SUBENTRY_CAM and sub.data.get("name") and sub.data.get("kuerzel"):
                data = {k: sub.data[k] for k in CAM_IMPORT_KEYS if k in sub.data}
            elif sub.subentry_type == SUBENTRY_PROFILE and sub.data.get("name"):
                data = dict(sub.data)
            else:
                continue
            out.append(
                {
                    "subentry_id": sid,
                    "subentry_type": sub.subentry_type,
                    "title": sub.title,
                    "unique_id": sub.unique_id,
                    "data": data,
                }
            )
    return out


def legacy_options(hass: HomeAssistant) -> dict[str, Any]:
    """Adresse und Schluessel des Recorders aus den alten Einstellungen (alte Add-on-Adresse -> neue)."""
    for entry in _legacy_entries(hass):
        url = entry.options.get(CONF_RECORDER_URL) or ""
        key = entry.options.get(CONF_RECORDER_KEY) or ""
        if url or key:
            out: dict[str, Any] = {CONF_RECORDER_URL: DEFAULT_RECORDER_URL if url.rstrip("/") == OLD_RECORDER_URL else url}
            if key:
                out[CONF_RECORDER_KEY] = key
            return out
    return {}


def import_into_entry(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, int]:
    """Fehlende Cams/Profile in einen bestehenden Eintrag uebernehmen (bereits vorhandene IDs bleiben unangetastet).

    Gibt es hier schon eine Cam gleichen Namens unter anderer ID, wird sie nicht doppelt angelegt; Profile, die auf die
    alte ID zeigen, werden auf die vorhandene Cam umgebogen.
    """
    added = {"cams": 0, "profile": 0, "uebersprungen": 0}
    own_by_unique = {s.unique_id: sid for sid, s in entry.subentries.items() if s.subentry_type == SUBENTRY_CAM and s.unique_id}
    items = legacy_subentries(hass)
    id_map: dict[str, str] = {}
    for item in items:  # erst Cams, damit die Profile danach umgebogen werden koennen
        if item["subentry_type"] != SUBENTRY_CAM:
            continue
        sid = item["subentry_id"]
        if sid in entry.subentries:
            continue
        if item["unique_id"] in own_by_unique:
            id_map[sid] = own_by_unique[item["unique_id"]]
            added["uebersprungen"] += 1
            continue
        _add(hass, entry, item)
        added["cams"] += 1
    for item in items:
        if item["subentry_type"] != SUBENTRY_PROFILE or item["subentry_id"] in entry.subentries:
            continue
        data = {**item["data"], "cams": [id_map.get(c, c) for c in item["data"].get("cams") or []]}
        _add(hass, entry, {**item, "data": data})
        added["profile"] += 1
    return added


def _add(hass: HomeAssistant, entry: ConfigEntry, item: dict[str, Any]) -> None:
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=item["data"],
            subentry_type=item["subentry_type"],
            title=item["title"],
            unique_id=item["unique_id"],
            subentry_id=item["subentry_id"],
        ),
    )


def import_available(hass: HomeAssistant) -> bool:
    return bool(legacy_subentries(hass)) and DOMAIN != LEGACY_DOMAIN
