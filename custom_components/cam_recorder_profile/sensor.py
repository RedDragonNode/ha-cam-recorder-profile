"""Sensoren: Status und freier Speicher."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CamRecorderConfigEntry
from .entity import CamRecorderEntity, hub_device
from .manager import CamRecorderManager


async def async_setup_entry(
    hass: HomeAssistant, entry: CamRecorderConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    m = entry.runtime_data
    async_add_entities([StatusSensor(m), RecorderSpaceSensor(m)])


class StatusSensor(CamRecorderEntity, SensorEntity):
    _attr_translation_key = "status"
    _attr_icon = "mdi:information-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, m: CamRecorderManager) -> None:
        super().__init__(m)
        self._attr_unique_id = f"{m.entry.entry_id}_status"
        self._attr_device_info = hub_device(m)

    @property
    def native_value(self) -> str | None:
        return self.manager.status_text

    @property
    def extra_state_attributes(self) -> dict:
        return {"zeit": self.manager.status_time}


class RecorderSpaceSensor(CamRecorderEntity, SensorEntity):
    """Freier Speicher am Aufnahme-Ort des Recorders."""

    _attr_translation_key = "recorder_frei"
    _attr_icon = "mdi:harddisk"
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, m: CamRecorderManager) -> None:
        super().__init__(m)
        self._attr_unique_id = f"{m.entry.entry_id}_recorder_frei"
        self._attr_device_info = hub_device(m)

    @property
    def available(self) -> bool:
        return bool(self.manager.rec_online)

    @property
    def native_value(self) -> float | None:
        return (self.manager.rec_status.get("speicher") or {}).get("frei_gb")

    @property
    def extra_state_attributes(self) -> dict:
        sp = self.manager.rec_status.get("speicher") or {}
        return {"gesamt_gb": sp.get("gesamt_gb"), "ordner": self.manager.rec_status.get("wurzel")}
