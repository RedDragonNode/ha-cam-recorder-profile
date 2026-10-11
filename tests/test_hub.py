"""Integration Cam Recorder Profile (Recorder-Add-on ist durch einen Fake ersetzt)."""
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cam_recorder_profile.const import DOMAIN
from custom_components.cam_recorder_profile.recorder_client import RecorderError

BASE = {"recorder_url": "http://addon:8099", "recorder_schluessel": "geheimgeheim123"}

CAMS = {
    "Fuchsblick": {"kuerzel": "FB", "rtsp_url": "rtsp://u:p@192.168.1.11:554/main"},
    "Kesselcam": {"kuerzel": "KC", "stream_entity": "camera.kessel"},
    "Rotpelz": {"kuerzel": "RP", "aufnehmen": False, "rtsp_url": "rtsp://x/y"},
    "Bauleitung": {"kuerzel": "BL"},
}


class FakeRecorder:
    """Ersatz fuer RecorderClient."""

    calls: list = []
    remote_profiles: dict = {}
    fail = False

    def __init__(self, *_a, **_k):
        pass

    def _chk(self):
        if FakeRecorder.fail:
            raise RecorderError("Recorder-Add-on nicht erreichbar (test)")

    async def status(self):
        self._chk()
        return {
            "aufnahme": bool(FakeRecorder.remote_profiles),
            "wurzel": "/media/Aufnahmen",
            "speicher": {"frei_gb": 2500.0, "gesamt_gb": 3000.0},
            "version": "0.4.0",
            "kameras": {},
            "profile": FakeRecorder.remote_profiles,
        }

    async def list_dirs(self, path):
        self._chk()
        return {"": ["Der_Fuchsbau", "Ueberwachung"], "Ueberwachung": ["Treppe"]}.get("/".join(path), [])

    async def start(self, path, cams, session, profile=None):
        self._chk()
        FakeRecorder.calls.append(("start", path, cams, session, profile))
        return {}

    async def stop(self, profile=None):
        self._chk()
        FakeRecorder.calls.append(("stop", profile))
        return {}


@pytest.fixture(autouse=True)
def fake_recorder():
    FakeRecorder.calls, FakeRecorder.remote_profiles, FakeRecorder.fail = [], {}, False
    with patch("custom_components.cam_recorder_profile.manager.RecorderClient", FakeRecorder), patch(
        "custom_components.cam_recorder_profile.config_flow.RecorderClient", FakeRecorder
    ):
        yield


def _stream_patch():
    return patch(
        "custom_components.cam_recorder_profile.manager.async_get_stream_source",
        AsyncMock(return_value="rtsp://k:k@192.168.1.12/stream"),
    )


def _cam_subs() -> list[ConfigSubentryData]:
    subs = []
    for name, extra in CAMS.items():
        data = {"name": name, "aufnehmen": True, "stream_entity": "", "rtsp_url": "", **extra}
        subs.append(
            ConfigSubentryData(subentry_type="cam", title=name, unique_id=name.lower(), subentry_id="cam_" + name, data=data)
        )
    return subs


async def _setup(hass: HomeAssistant, profiles: list[dict] | None = None, **extra) -> MockConfigEntry:
    subs = _cam_subs()
    for prof in profiles or []:
        subs.append(
            ConfigSubentryData(
                subentry_type="profil", title=prof["name"], unique_id=prof["name"].lower(), subentry_id="prof_" + prof["name"], data=prof
            )
        )
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={**BASE, **extra}, subentries_data=subs, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _prof(name, cams, **kw):
    return {
        "name": name,
        "ordner": kw.pop("ordner", f"Ueberwachung/{name}"),
        "cams": [f"cam_{c}" for c in cams],
        "dateimuster": "{cam} %CCYY",
        "ausloeser": [],
        "nachlauf_sekunden": 0,
        "max_dauer_minuten": 0,
        "zeit_von": "",
        "zeit_bis": "",
        "sonne": "",
        **kw,
    }


async def test_motion_trigger_starts_and_stops_with_own_profile_id(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.treppe", "off")
    await _setup(hass, [_prof("Treppe", ["Fuchsblick"], ausloeser=["binary_sensor.treppe"])])
    hass.states.async_set("binary_sensor.treppe", "on")
    await hass.async_block_till_done()
    kind, path, cams, session, profile = FakeRecorder.calls[-1]
    assert kind == "start" and path == ["Ueberwachung", "Treppe"] and cams[0]["id"] == "cam_Fuchsblick"
    assert profile == "prof_Treppe" and session.startswith("Treppe ")
    assert cams[0]["stem"] == f"Fuchsblick {dt_util.now().year}"
    hass.states.async_set("binary_sensor.treppe", "off")
    await hass.async_block_till_done()
    assert FakeRecorder.calls[-1] == ("stop", "prof_Treppe")  # nie ein Stopp ohne Profil (der wuerde alle Sitzungen beenden)


async def test_run_on_delay_and_manual_services(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.flur", "off")
    entry = await _setup(hass, [_prof("Flur", ["Fuchsblick"], ausloeser=["binary_sensor.flur"], nachlauf_sekunden=3600)])
    m = entry.runtime_data
    hass.states.async_set("binary_sensor.flur", "on")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.flur", "off")
    await hass.async_block_till_done()
    assert m.profile_running("prof_Flur")  # Nachlauf laeuft noch
    await hass.services.async_call(DOMAIN, "profil_stoppen", {"profil": "Flur"}, blocking=True)
    assert not m.profile_running("prof_Flur") and FakeRecorder.calls[-1] == ("stop", "prof_Flur")
    await hass.services.async_call(DOMAIN, "profil_starten", {"profil": "flur"}, blocking=True)
    assert m.profile_running("prof_Flur")
    hass.states.async_set("binary_sensor.flur", "on")
    hass.states.async_set("binary_sensor.flur", "off")
    await hass.async_block_till_done()
    assert m.profile_running("prof_Flur")  # manuell gestartet: Ausloeser stoppt nicht
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "profil_starten", {"profil": "gibtsnicht"}, blocking=True)


async def test_cam_in_two_profiles_only_records_once(hass: HomeAssistant) -> None:
    entry = await _setup(hass, [_prof("A", ["Fuchsblick"]), _prof("B", ["Fuchsblick", "Rotpelz", "Kesselcam"])])
    m = entry.runtime_data
    with _stream_patch():
        await hass.services.async_call(DOMAIN, "profil_starten", {"profil": "A"}, blocking=True)
        res = await hass.services.async_call(DOMAIN, "profil_starten", {"profil": "B"}, blocking=True, return_response=True)
    assert res["cams"] == ["Kesselcam"] and any("belegt" in x for x in res["uebersprungen"])
    assert m.profile_running("prof_A") and m.profile_running("prof_B")


async def test_cam_busy_in_spielpartner_session_is_skipped(hass: HomeAssistant) -> None:
    """Der Spielpartner-Ablauf laeuft im Add-on als Sitzung 'default' - das Profil muss diese Cams auslassen."""
    entry = await _setup(hass, [_prof("A", ["Fuchsblick", "Kesselcam"])])
    FakeRecorder.remote_profiles = {"default": {"aufnahme": True, "kameras": {"cam_Fuchsblick": {"status": "nimmt auf"}}}}
    with _stream_patch():
        res = await hass.services.async_call(DOMAIN, "profil_starten", {"profil": "A"}, blocking=True, return_response=True)
    assert res["cams"] == ["Kesselcam"] and any("Fuchsblick" in x and "belegt" in x for x in res["uebersprungen"])
    assert entry.runtime_data.profile_running("prof_A")


async def test_manual_start_without_free_cam_fails_but_trigger_start_is_quiet(hass: HomeAssistant) -> None:
    entry = await _setup(hass, [_prof("A", ["Bauleitung"])])  # Cam ohne Stream-Quelle
    with pytest.raises(ServiceValidationError):
        await entry.runtime_data.async_profile_start("A")
    r = await entry.runtime_data._profile_start(entry.runtime_data.profile("A"), manual=False)
    assert r["gestartet"] is False and not FakeRecorder.calls


async def test_unreachable_addon_does_not_mark_running(hass: HomeAssistant) -> None:
    entry = await _setup(hass, [_prof("A", ["Fuchsblick"])])
    FakeRecorder.fail = True
    with pytest.raises(RecorderError):
        await entry.runtime_data.async_profile_start("A")
    assert not entry.runtime_data.profile_running("prof_A") and entry.runtime_data.rec_online is False


async def test_sun_window(hass: HomeAssistant) -> None:
    hass.states.async_set("sun.sun", "above_horizon")
    with _stream_patch():
        entry = await _setup(hass, [_prof("Nacht", ["Fuchsblick"], sonne="nacht"), _prof("Tag", ["Kesselcam"], sonne="tag")])
        m = entry.runtime_data
        assert m.profile_running("prof_Tag") and not m.profile_running("prof_Nacht")
        hass.states.async_set("sun.sun", "below_horizon")
        await hass.async_block_till_done()
        await m._profile_tick(None)
    assert m.profile_running("prof_Nacht") and not m.profile_running("prof_Tag")


async def test_max_duration_and_lost_detection(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.x", "on")
    entry = await _setup(hass, [_prof("X", ["Fuchsblick"], ausloeser=["binary_sensor.x"], max_dauer_minuten=1)])
    m = entry.runtime_data
    assert m.profile_running("prof_X")
    m.profile_state["prof_X"]["start"] = (dt_util.utcnow() - timedelta(minutes=2)).isoformat()
    await m._profile_tick(None)
    assert not m.profile_running("prof_X")
    await m._profile_tick(None)
    assert not m.profile_running("prof_X")  # Trigger noch an, aber Hoechstdauer erreicht -> kein Neustart
    hass.states.async_set("binary_sensor.x", "off")
    await m._profile_tick(None)
    hass.states.async_set("binary_sensor.x", "on")
    await hass.async_block_till_done()
    assert m.profile_running("prof_X")
    await m._sync_profiles({"profile": {"prof_X": {"aufnahme": False, "stop_grund": "speicher_voll"}}})
    assert not m.profile_running("prof_X")


async def test_running_profile_is_readopted_after_restart(hass: HomeAssistant) -> None:
    FakeRecorder.remote_profiles = {"prof_A": {"aufnahme": True, "kameras": {"cam_Fuchsblick": {"status": "nimmt auf"}}}}
    entry = await _setup(hass, [_prof("A", ["Fuchsblick"])])
    await entry.runtime_data._poll_recorder(None)  # der erste Abgleich laeuft sonst als Hintergrundaufgabe
    assert entry.runtime_data.profile_running("prof_A")
    assert entry.runtime_data.profile_state["prof_A"]["cams"] == ["cam_Fuchsblick"]


async def test_setup_entities_and_dispatch(hass: HomeAssistant) -> None:
    from homeassistant.helpers import entity_registry as er

    entry = await _setup(hass, [_prof("A", ["Fuchsblick"])])
    ids = {e.unique_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    assert sum(1 for i in ids if "_cam_" in i and i.endswith("_aufnahme")) == len(CAMS)
    assert f"{entry.entry_id}_prof_prof_A_aufnahme" in ids
    assert {f"{entry.entry_id}_recorder_online", f"{entry.entry_id}_status", f"{entry.entry_id}_recorder_frei"} <= ids
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_cam_subentry_flow(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "cam"), context={"source": "user"})
    dup = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"name": "fuchsblick", "kuerzel": "X"})
    assert dup["errors"] == {"name": "already_configured"}
    done = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "Neu", "kuerzel": " NE ", "rtsp_url": " rtsp://h/s "}
    )
    assert done["type"] == "create_entry"
    sub = next(s for s in entry.subentries.values() if s.data["name"] == "Neu")
    assert sub.data["kuerzel"] == "NE" and sub.data["rtsp_url"] == "rtsp://h/s" and sub.data["aufnehmen"] is True
    # bearbeiten
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "cam"), context={"source": "reconfigure", "subentry_id": "cam_Kesselcam"}
    )
    assert flow["type"] == "form" and "rtsp_url" in {str(k) for k in flow["data_schema"].schema}
    done = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"kuerzel": "KK", "stream_entity": "camera.kessel"})
    assert done["type"] == "abort" and entry.subentries["cam_Kesselcam"].data["kuerzel"] == "KK"


async def test_profile_subentry_flow(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "profil"), context={"source": "user"})
    bad = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"name": "T", "ordner": "A", "cams": []})
    assert bad["errors"] == {"cams": "cams_required"}
    opts = next(k for k in flow["data_schema"].schema if str(k) == "ordner")
    values = [o["value"] for o in flow["data_schema"].schema[opts].config["options"]]
    assert values == ["Der_Fuchsbau", "Ueberwachung", "Ueberwachung/Treppe"]  # Unterordner stehen mit in der Auswahl
    ok = await hass.config_entries.subentries.async_configure(
        flow["flow_id"],
        {"name": "Treppe", "ordner": "Ueberwachung/Treppe", "cams": ["cam_Fuchsblick"], "zeit_von": "22:00:00", "zeit_bis": "06:00:00"},
    )
    assert ok["type"] == "create_entry"
    sub = next(s for s in entry.subentries.values() if s.subentry_type == "profil")
    assert sub.data["ordner"] == "Ueberwachung/Treppe" and sub.data["dateimuster"].startswith("{cam}")


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    res = await hass.config_entries.options.async_init(entry.entry_id)
    res = await hass.config_entries.options.async_configure(res["flow_id"], {**BASE, "recorder_url": "http://neu:8099"})
    assert res["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["recorder_url"] == "http://neu:8099"


# ---------------------------------------------------------------- Uebernahme aus Spielpartner Aufnahme
def _legacy_entry(hass: HomeAssistant) -> MockConfigEntry:
    subs = [
        ConfigSubentryData(
            subentry_type="cam",
            title="Fuchsblick",
            unique_id="fuchsblick",
            subentry_id="old_cam_1",
            data={"name": "Fuchsblick", "kuerzel": "FB", "kamera_entity": "camera.fb", "discord_posten": True,
                  "aufnehmen": True, "stream_entity": "", "rtsp_url": "rtsp://a/b"},
        ),
        ConfigSubentryData(
            subentry_type="cam", title="Nachtsicht", unique_id="nachtsicht", subentry_id="old_cam_2",
            data={"name": "Nachtsicht", "kuerzel": "NS", "kamera_entity": "", "discord_posten": False,
                  "aufnehmen": True, "stream_entity": "", "rtsp_url": "rtsp://c/d"},
        ),
        ConfigSubentryData(
            subentry_type="profil", title="Treppe", unique_id="treppe", subentry_id="old_prof_1",
            data=_prof("Treppe", []) | {"cams": ["old_cam_1", "old_cam_2"]},
        ),
        ConfigSubentryData(subentry_type="spielpartner", title="Frank", unique_id="frank", subentry_id="old_p",
                           data={"kennung": "frank", "anzeige": "Frank", "ordner_nr": 1}),
    ]
    legacy = MockConfigEntry(
        domain="spielpartner_aufnahme", data={}, subentries_data=subs,
        options={"recorder_url": "http://local-spielpartner-recorder:8099", "recorder_schluessel": "geheimgeheim123", "discord_token": "x"},
    )
    legacy.add_to_hass(hass)
    return legacy


async def test_config_flow_imports_legacy_cams_with_same_ids(hass: HomeAssistant) -> None:
    _legacy_entry(hass)
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert res["type"] == "form" and "uebernehmen" in {str(k) for k in res["data_schema"].schema}
    keys = {str(k): k.description for k in res["data_schema"].schema if str(k) == "recorder_url"}
    assert keys["recorder_url"]["suggested_value"] == "http://local-cam-recorder:8099"  # alte Add-on-Adresse ersetzt
    res = await hass.config_entries.flow.async_configure(
        res["flow_id"], {"recorder_url": "http://local-cam-recorder:8099", "recorder_schluessel": "geheimgeheim123", "uebernehmen": True}
    )
    assert res["type"] == "create_entry"
    entry = res["result"]
    await hass.async_block_till_done()
    assert set(entry.subentries) == {"old_cam_1", "old_cam_2", "old_prof_1"}  # Spielpartner-Subentry bleibt dort
    cam = entry.subentries["old_cam_1"].data
    assert cam["rtsp_url"] == "rtsp://a/b" and "kamera_entity" not in cam and "discord_posten" not in cam
    assert entry.runtime_data.profiles["old_prof_1"].name == "Treppe"
    assert sorted(c.subentry_id for c in entry.runtime_data.cams) == ["old_cam_1", "old_cam_2"]


async def test_config_flow_without_legacy_has_no_import_option(hass: HomeAssistant) -> None:
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert "uebernehmen" not in {str(k) for k in res["data_schema"].schema}
    res = await hass.config_entries.flow.async_configure(res["flow_id"], BASE)
    assert res["type"] == "create_entry" and not res["result"].subentries


async def test_import_service_adds_only_missing(hass: HomeAssistant) -> None:
    entry = await _setup(hass)  # hat schon "Fuchsblick" (andere ID), aber nicht "Nachtsicht"
    _legacy_entry(hass)
    res = await hass.services.async_call(DOMAIN, "cams_uebernehmen", {}, blocking=True, return_response=True)
    assert res == {"cams": 1, "profile": 1, "uebersprungen": 1}
    await hass.async_block_till_done()
    assert "old_cam_1" not in entry.subentries  # gleiche Cam existiert schon -> nicht doppelt
    assert "old_cam_2" in entry.subentries
    assert entry.subentries["old_prof_1"].data["cams"] == ["cam_Fuchsblick", "old_cam_2"]  # auf vorhandene Cam umgebogen
    again = await hass.services.async_call(DOMAIN, "cams_uebernehmen", {}, blocking=True, return_response=True)
    assert again == {"cams": 0, "profile": 0, "uebersprungen": 1}
