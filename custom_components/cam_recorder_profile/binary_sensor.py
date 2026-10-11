"""Binaersensoren: Recorder erreichbar, Aufnahme je Cam und je Profil."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CamRecorderConfigEntry
from .const import SUBENTRY_CAM, SUBENTRY_PROFILE
from .entity import CamRecorderEntity, cam_device, hub_device, profile_device
from .manager import CamCfg, CamRecorderManager, ProfileCfg


async def async_setup_entry(
    hass: HomeAssistant, entry: CamRecorderConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    m = entry.runtime_data
    async_add_entities([RecorderOnlineSensor(m)])
    for sid, sub in entry.subentries.items():
        if sub.subentry_type == SUBENTRY_CAM:
            cam = next(c for c in m.cams if c.subentry_id == sid)
            async_add_entities([CamRecordingSensor(m, cam)], config_subentry_id=sid)
        elif sub.subentry_type == SUBENTRY_PROFILE:
            async_add_entities([ProfileRecordingSensor(m, m.profiles[sid])], config_subentry_id=sid)


class RecorderOnlineSensor(CamRecorderEntity, BinarySensorEntity):
    _attr_translation_key = "recorder_online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, m: CamRecorderManager) -> None:
        super().__init__(m)
        self._attr_unique_id = f"{m.entry.entry_id}_recorder_online"
        self._attr_device_info = hub_device(m)

    @property
    def is_on(self) -> bool:
        return bool(self.manager.rec_online)

    @property
    def extra_state_attributes(self) -> dict:
        return {"version": self.manager.rec_status.get("version")}


class CamRecordingSensor(CamRecorderEntity, BinarySensorEntity):
    """Nimmt diese Cam gerade auf - egal in welcher Sitzung (Profil oder Spielpartner-Ablauf)."""

    _attr_translation_key = "cam_aufnahme"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, m: CamRecorderManager, cam: CamCfg) -> None:
        super().__init__(m)
        self.cam = cam
        self._attr_unique_id = f"{m.entry.entry_id}_cam_{cam.subentry_id}_aufnahme"
        self._attr_device_info = cam_device(m, cam)

    def _info(self) -> dict:
        return (self.manager.rec_status.get("kameras") or {}).get(self.cam.subentry_id) or {}

    @property
    def is_on(self) -> bool:
        return self._info().get("status") == "nimmt auf"

    @property
    def extra_state_attributes(self) -> dict:
        i = self._info()
        return {
            "status": i.get("status"),
            "datei": i.get("datei"),
            "teil": i.get("teil"),
            "neustarts": i.get("neustarts"),
            "groesse_mb": round((i.get("bytes") or 0) / 1e6, 1),
            "letzter_fehler": i.get("letzter_fehler") or None,
        }


class ProfileRecordingSensor(CamRecorderEntity, BinarySensorEntity):
    _attr_translation_key = "profil_aufnahme"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, m: CamRecorderManager, profile: ProfileCfg) -> None:
        super().__init__(m)
        self.profile = profile
        self._attr_unique_id = f"{m.entry.entry_id}_prof_{profile.subentry_id}_aufnahme"
        self._attr_device_info = profile_device(m, profile)

    @property
    def is_on(self) -> bool:
        return self.manager.profile_running(self.profile.subentry_id)

    @property
    def extra_state_attributes(self) -> dict:
        run = self.manager.profile_state.get(self.profile.subentry_id) or {}
        names = {c.subentry_id: c.name for c in self.manager.cams}
        return {
            "ordner": "/".join(self.profile.folder),
            "seit": run.get("start"),
            "manuell": run.get("manual"),
            "cams": [names.get(c, c) for c in run.get("cams", [])] or [names.get(c, c) for c in self.profile.cam_ids],
        }
