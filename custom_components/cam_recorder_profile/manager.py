"""Kern der Integration: Cams, Aufnahme-Profile und Abgleich mit dem Recorder-Add-on."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from . import logic
from .const import (
    CONF_CAM_KUERZEL,
    CONF_CAM_NAME,
    CONF_CAM_RECORD,
    CONF_CAM_RTSP,
    CONF_CAM_STREAM,
    CONF_PROF_AFTER,
    CONF_PROF_CAMS,
    CONF_PROF_FOLDER,
    CONF_PROF_FROM,
    CONF_PROF_MAX,
    CONF_PROF_NAME,
    CONF_PROF_PATTERN,
    CONF_PROF_SUN,
    CONF_PROF_TO,
    CONF_PROF_TRIGGERS,
    CONF_RECORDER_KEY,
    CONF_RECORDER_URL,
    DEFAULT_OPTIONS,
    DEFAULT_PATTERN,
    DOMAIN,
    SUBENTRY_CAM,
    SUBENTRY_PROFILE,
)
from .recorder_client import RecorderClient, RecorderError

_LOGGER = logging.getLogger(__name__)


async def async_get_stream_source(hass: HomeAssistant, entity_id: str) -> str | None:
    """RTSP-Adresse einer HA-Kamera holen (Camera-Komponente erst bei Bedarf laden)."""
    from homeassistant.components.camera import async_get_stream_source as _get

    return await _get(hass, entity_id)


@dataclass
class CamCfg:
    """Eine Cam. Die ID (subentry_id) ist zugleich die Cam-ID im Recorder-Add-on."""

    subentry_id: str
    name: str
    kuerzel: str
    record: bool = True
    stream_entity: str = ""
    rtsp_url: str = ""


@dataclass
class ProfileCfg:
    """Aufnahme-Profil: wohin, welche Cams, wann."""

    subentry_id: str
    name: str
    folder: list[str]
    cam_ids: list[str]
    pattern: str = DEFAULT_PATTERN
    triggers: list[str] = field(default_factory=list)
    after_s: int = 0
    max_min: int = 0
    time_from: str = ""
    time_to: str = ""
    sun: str = ""

    @property
    def has_window(self) -> bool:
        return bool((self.time_from and self.time_to) or self.sun)


class CamRecorderManager:
    """Haelt Cams und Profile eines Config-Entries und steuert die Profil-Aufnahmen."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.signal = f"{DOMAIN}_update_{entry.entry_id}"
        self._unsubs: list[CALLBACK_TYPE] = []
        self.rec_status: dict[str, Any] = {}
        self.rec_online: bool | None = None
        self.status_text: str | None = None
        self.status_time: str | None = None
        self.cams: list[CamCfg] = []
        self.profiles: dict[str, ProfileCfg] = {}
        self.profile_state: dict[str, dict[str, Any]] = {}  # laufende Profile (Laufzeit)
        self._prof_lock = asyncio.Lock()
        self._capped: set[str] = set()
        self._read_subentries()

    # ------------------------------------------------------------------ Setup
    def _read_subentries(self) -> None:
        for sid, sub in self.entry.subentries.items():
            d = sub.data
            if sub.subentry_type == SUBENTRY_CAM:
                self.cams.append(
                    CamCfg(
                        subentry_id=sid,
                        name=d[CONF_CAM_NAME],
                        kuerzel=d[CONF_CAM_KUERZEL],
                        record=bool(d.get(CONF_CAM_RECORD, True)),
                        stream_entity=d.get(CONF_CAM_STREAM, "") or "",
                        rtsp_url=d.get(CONF_CAM_RTSP, "") or "",
                    )
                )
            elif sub.subentry_type == SUBENTRY_PROFILE:
                self.profiles[sid] = ProfileCfg(
                    subentry_id=sid,
                    name=d[CONF_PROF_NAME],
                    folder=logic.split_path(d.get(CONF_PROF_FOLDER, "")),
                    cam_ids=list(d.get(CONF_PROF_CAMS) or []),
                    pattern=d.get(CONF_PROF_PATTERN) or DEFAULT_PATTERN,
                    triggers=list(d.get(CONF_PROF_TRIGGERS) or []),
                    after_s=int(d.get(CONF_PROF_AFTER) or 0),
                    max_min=int(d.get(CONF_PROF_MAX) or 0),
                    time_from=d.get(CONF_PROF_FROM) or "",
                    time_to=d.get(CONF_PROF_TO) or "",
                    sun=d.get(CONF_PROF_SUN) or "",
                )
        self.cams.sort(key=lambda c: logic.norm(c.name))

    @callback
    def async_start(self) -> None:
        watch = {e for p in self.profiles.values() for e in p.triggers}
        if any(p.sun for p in self.profiles.values()):
            watch.add("sun.sun")
        if watch:
            self._unsubs.append(async_track_state_change_event(self.hass, sorted(watch), self._profile_state_changed))
        if self.profiles:
            self._unsubs.append(async_track_time_interval(self.hass, self._profile_tick, timedelta(seconds=20)))
        if self.opt(CONF_RECORDER_URL):
            self._unsubs.append(async_track_time_interval(self.hass, self._poll_recorder, timedelta(seconds=15)))
            self.hass.async_create_background_task(self._first_sync(), name=f"{DOMAIN}_poll")
        elif self.profiles:
            self.hass.async_create_background_task(self._profile_tick(None), name=f"{DOMAIN}_profiles")

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # ---------------------------------------------------------------- Helfer
    def opt(self, key: str) -> Any:
        val = self.entry.options.get(key)
        return DEFAULT_OPTIONS.get(key) if val is None and key in DEFAULT_OPTIONS else val

    @callback
    def notify(self) -> None:
        async_dispatcher_send(self.hass, self.signal)

    def _set_status(self, text: str) -> None:
        self.status_text, self.status_time = text, dt_util.now().isoformat()

    def _recorder(self) -> RecorderClient:
        url, key = self.opt(CONF_RECORDER_URL), self.opt(CONF_RECORDER_KEY)
        if not url or not key:
            raise ServiceValidationError("Recorder: Adresse und Schluessel fehlen in den Einstellungen")
        return RecorderClient(async_get_clientsession(self.hass), url, key)

    def cam(self, cam_id: str) -> CamCfg | None:
        return next((c for c in self.cams if c.subentry_id == cam_id), None)

    async def _stream_url(self, cam: CamCfg) -> str | None:
        if cam.rtsp_url:
            return cam.rtsp_url
        if cam.stream_entity:
            try:
                return await async_get_stream_source(self.hass, cam.stream_entity)
            except HomeAssistantError as err:
                _LOGGER.warning("Stream-Quelle von %s nicht lesbar: %s", cam.stream_entity, err)
        return None

    # ------------------------------------------------------------------ Recorder
    async def _poll_recorder(self, _now: datetime | None) -> None:
        """Zustand des Add-ons holen; verlorene Profil-Aufnahmen (Absturz, Platte voll) erkennen."""
        try:
            st = await self._recorder().status()
        except (RecorderError, ServiceValidationError):
            if self.rec_online is not False:
                self.rec_online = False
                self.notify()
            return
        self.rec_status, self.rec_online = st, True
        await self._sync_profiles(st)
        self.notify()

    async def _first_sync(self) -> None:
        """Beim Start erst den Add-on-Stand holen (laufende Profile erkennen), dann Ausloeser auswerten."""
        await self._poll_recorder(None)
        await self._profile_tick(None)

    # ------------------------------------------------------------------ Profile
    def profile(self, ref: str) -> ProfileCfg:
        if ref in self.profiles:
            return self.profiles[ref]
        norm = logic.norm(ref)
        for p in self.profiles.values():
            if norm == logic.norm(p.name):
                return p
        raise ServiceValidationError(f"Aufnahme-Profil '{ref}' gibt es nicht")

    def profile_running(self, pid: str) -> bool:
        return pid in self.profile_state

    def _busy_cam_ids(self, exclude: str) -> set[str]:
        """Cams, die gerade in einer anderen Sitzung aufnehmen.

        Quelle der Wahrheit ist der Add-on-Stand: er enthaelt auch Sitzungen anderer Integrationen
        (z. B. den Spielpartner-Ablauf, Profil-ID 'default'). Dazu der eigene Merker fuer gerade gestartete Profile.
        """
        busy: set[str] = set()
        for pid, st in self.profile_state.items():
            if pid != exclude:
                busy |= set(st.get("cams") or [])
        for pid, ps in (self.rec_status.get("profile") or {}).items():
            if pid != exclude and ps.get("aufnahme"):
                busy |= {k for k, c in (ps.get("kameras") or {}).items() if c.get("status") != "beendet"}
        return busy

    def _trigger_on(self, p: ProfileCfg) -> bool:
        return any((st := self.hass.states.get(e)) is not None and st.state == STATE_ON for e in p.triggers)

    def _window_open(self, p: ProfileCfg, now: datetime) -> bool:
        if p.time_from and p.time_to and not logic.in_time_window(now, p.time_from, p.time_to):
            return False
        if p.sun:
            sun = self.hass.states.get("sun.sun")
            if sun is None or sun.state not in ("above_horizon", "below_horizon"):
                return False
            if (sun.state == "above_horizon") != (p.sun == "tag"):
                return False
        return True

    def _wanted(self, p: ProfileCfg, now: datetime) -> bool:
        if not p.triggers and not p.has_window:
            return False  # nur manuell
        if not self._window_open(p, now):
            return False
        return self._trigger_on(p) if p.triggers else True

    @callback
    def _profile_state_changed(self, _event: Event[EventStateChangedData]) -> None:
        self.hass.async_create_task(self._profile_tick(None))

    async def _profile_tick(self, _now: datetime | None) -> None:
        """Gleicht jedes Profil mit seinen Ausloesern ab (Start, Nachlauf, Hoechstdauer, Zeitfenster)."""
        async with self._prof_lock:
            now = dt_util.now()
            for p in list(self.profiles.values()):
                try:
                    await self._reconcile(p, now)
                except HomeAssistantError as err:
                    _LOGGER.error("Profil %s: %s", p.name, err)
                    self._set_status(f"Profil {p.name}: {err}")
                    self.notify()

    async def _reconcile(self, p: ProfileCfg, now: datetime) -> None:
        run = self.profile_state.get(p.subentry_id)
        wanted = self._wanted(p, now)
        if not wanted:
            self._capped.discard(p.subentry_id)  # Trigger vorbei -> naechste Runde darf wieder starten
        if run is None:
            if wanted and p.subentry_id not in self._capped:
                await self._profile_start(p, manual=False)
            return
        if run.get("manual"):
            return
        if wanted:
            run["off_since"] = None
            if p.max_min and (dt_util.utcnow() - dt_util.parse_datetime(run["start"])).total_seconds() >= p.max_min * 60:
                self._capped.add(p.subentry_id)
                await self._profile_stop(p, "hoechstdauer")
            return
        if p.has_window and not self._window_open(p, now):
            await self._profile_stop(p, "zeitfenster")
            return
        off = run.get("off_since")
        if off is None:
            run["off_since"] = dt_util.utcnow().isoformat()
            off = run["off_since"]
        if (dt_util.utcnow() - dt_util.parse_datetime(off)).total_seconds() >= p.after_s:
            await self._profile_stop(p, "ausloeser_aus")

    async def async_profile_start(self, ref: str) -> dict[str, Any]:
        p = self.profile(ref)
        async with self._prof_lock:
            if p.subentry_id in self.profile_state:
                return {"gestartet": False, "grund": "Profil nimmt bereits auf"}
            return await self._profile_start(p, manual=True)

    async def async_profile_stop(self, ref: str) -> dict[str, Any]:
        p = self.profile(ref)
        async with self._prof_lock:
            if p.subentry_id not in self.profile_state:
                return {"gestoppt": False, "grund": "Profil nimmt nicht auf"}
            await self._profile_stop(p, "manuell")
            return {"gestoppt": True}

    async def _profile_start(self, p: ProfileCfg, manual: bool) -> dict[str, Any]:
        client = self._recorder()
        try:  # frischer Add-on-Stand, damit Aufnahmen anderer Sitzungen (z. B. Spielpartner) nicht uebersehen werden
            self.rec_status, self.rec_online = await client.status(), True
        except RecorderError as err:
            self.rec_online = False
            self._set_status(f"Profil {p.name}: Start fehlgeschlagen: {err}")
            self.notify()
            if manual:
                raise
            _LOGGER.warning("Profil %s konnte nicht starten: %s", p.name, err)
            return {"gestartet": False, "grund": str(err)}
        busy = self._busy_cam_ids(p.subentry_id)
        now = dt_util.now()
        cams: list[dict[str, str]] = []
        skipped: list[str] = []
        for cid in p.cam_ids:
            cam = self.cam(cid)
            if cam is None or not cam.record:
                continue
            if cid in busy:
                skipped.append(f"{cam.name} (belegt)")
                continue
            url = await self._stream_url(cam)
            if not url:
                skipped.append(f"{cam.name} (keine Stream-Quelle)")
                continue
            stem = logic.render_pattern(p.pattern, now, cam=cam.name, kuerzel=cam.kuerzel, profil=p.name)
            cams.append({"id": cid, "name": cam.name, "url": url, "stem": stem})
        if not cams:
            if manual:
                raise ServiceValidationError(
                    f"Profil {p.name}: keine Cam frei oder ohne Stream-Quelle ({', '.join(skipped) or 'keine Cams gewaehlt'})"
                )
            return {"gestartet": False, "grund": "keine Cam verfuegbar", "uebersprungen": skipped}
        session = logic.render_pattern("{profil} %CCYY-%MM-%DD %hh-%mm-%ss", now, cam="", kuerzel="", profil=p.name)
        try:
            await client.start(p.folder, cams, session, p.subentry_id)
        except RecorderError as err:
            if "nicht erreichbar" in str(err):
                self.rec_online = False
            self._set_status(f"Profil {p.name}: Start fehlgeschlagen: {err}")
            self.notify()
            if manual:
                raise
            _LOGGER.warning("Profil %s konnte nicht starten: %s", p.name, err)
            return {"gestartet": False, "grund": str(err)}
        self.profile_state[p.subentry_id] = {
            "start": dt_util.utcnow().isoformat(),
            "manual": manual,
            "cams": [c["id"] for c in cams],
            "off_since": None,
        }
        self._set_status(f"Profil {p.name}: nimmt auf ({len(cams)} Cams)")
        self.notify()
        return {"gestartet": True, "cams": [c["name"] for c in cams], "uebersprungen": skipped, "ordner": "/".join(p.folder)}

    async def _profile_stop(self, p: ProfileCfg, reason: str) -> None:
        client = self._recorder()
        try:
            await client.stop(p.subentry_id)
        except RecorderError as err:
            self._set_status(f"Profil {p.name}: Stoppen fehlgeschlagen: {err}")
            self.notify()
            raise
        self.profile_state.pop(p.subentry_id, None)
        self._set_status(f"Profil {p.name}: Aufnahme beendet ({reason})")
        self.notify()

    async def _sync_profiles(self, st: dict[str, Any]) -> None:
        """Add-on-Stand uebernehmen: nach HA-Neustart weiterlaufende Profile erkennen, verlorene melden."""
        if "profile" not in st:
            return
        remote = st["profile"]
        for pid, p in self.profiles.items():
            ps = remote.get(pid) or {}
            if ps.get("aufnahme") and pid not in self.profile_state:
                cams = [k for k, c in (ps.get("kameras") or {}).items() if c.get("status") != "beendet"]
                self.profile_state[pid] = {"start": dt_util.utcnow().isoformat(), "manual": False, "cams": cams, "off_since": None}
            elif not ps.get("aufnahme") and pid in self.profile_state and not self._prof_lock.locked():
                self.profile_state.pop(pid, None)
                reason = ps.get("stop_grund") or "unbekannt (Add-on neu gestartet?)"
                persistent_notification.async_create(
                    self.hass,
                    f"Das Profil '{p.name}' wurde vom Recorder beendet. Grund: {reason}.",
                    title="Recorder: Profil unerwartet beendet",
                    notification_id=f"{DOMAIN}_profile_lost_{pid}",
                )
                self._set_status(f"Profil {p.name}: beendet - Grund: {reason}")
