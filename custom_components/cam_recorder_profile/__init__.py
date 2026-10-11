"""Cam Recorder Profile: Cams und Aufnahme-Profile fuer das Recorder-Add-on 'Cam Recorder'."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    SERVICE_IMPORT,
    SERVICE_PROFILE_START,
    SERVICE_PROFILE_STOP,
    SIGNAL_LOADED,
    SUBENTRY_CAM,
    SUBENTRY_PROFILE,
)
from .entity import cam_device, profile_device
from .importer import import_into_entry
from .manager import CamRecorderManager

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type CamRecorderConfigEntry = ConfigEntry[CamRecorderManager]


def _entry(hass: HomeAssistant) -> CamRecorderConfigEntry:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if getattr(entry, "runtime_data", None) is not None:
            return entry
    raise ServiceValidationError("Cam Recorder Profile ist nicht eingerichtet oder nicht geladen")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def prof_start(call: ServiceCall) -> dict:
        return await _entry(hass).runtime_data.async_profile_start(call.data["profil"])

    async def prof_stop(call: ServiceCall) -> dict:
        return await _entry(hass).runtime_data.async_profile_stop(call.data["profil"])

    async def import_cams(call: ServiceCall) -> dict:
        return import_into_entry(hass, _entry(hass))

    for name, handler in ((SERVICE_PROFILE_START, prof_start), (SERVICE_PROFILE_STOP, prof_stop)):
        hass.services.async_register(
            DOMAIN, name, handler, vol.Schema({vol.Required("profil"): cv.string}), supports_response=SupportsResponse.OPTIONAL
        )
    hass.services.async_register(DOMAIN, SERVICE_IMPORT, import_cams, vol.Schema({}), supports_response=SupportsResponse.OPTIONAL)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CamRecorderConfigEntry) -> bool:
    manager = CamRecorderManager(hass, entry)
    entry.runtime_data = manager

    registry = dr.async_get(hass)
    hub = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Cam Recorder Profile",
        manufacturer="RedDragonNode",
        model="Aufnahme-Profile",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    for sid, sub in entry.subentries.items():
        if sub.subentry_type == SUBENTRY_CAM:
            cam = manager.cam(sid)
            info = cam_device(manager, cam) if cam else None
        elif sub.subentry_type == SUBENTRY_PROFILE:
            info = profile_device(manager, manager.profiles[sid])
        else:
            info = None
        if info:
            device = registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                config_subentry_id=sid,
                identifiers=info["identifiers"],
                name=info["name"],
                manufacturer=info["manufacturer"],
                model=info["model"],
            )
            registry.async_update_device(device.id, via_device_id=hub.id)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.async_start()
    entry.async_on_unload(entry.add_update_listener(_reload_on_change))
    async_dispatcher_send(hass, SIGNAL_LOADED)  # Spielpartner Aufnahme liest die Cam-Liste neu ein
    return True


async def _reload_on_change(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Cams/Profile oder Einstellungen wurden geaendert -> neu laden."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: CamRecorderConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_stop()
    return ok
