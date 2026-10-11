"""Config-Flow, Optionen und Subentries (Cams / Aufnahme-Profile)."""
from __future__ import annotations

from typing import Any, cast

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import logic
from .const import (
    CONF_CAM_KUERZEL,
    CONF_CAM_NAME,
    CONF_CAM_RECORD,
    CONF_CAM_RTSP,
    CONF_CAM_STREAM,
    CONF_IMPORT,
    CONF_PROF_AFTER,
    CONF_PROF_CAMS,
    CONF_PROF_FOLDER,
    CONF_PROF_FROM,
    CONF_PROF_MAIN,
    CONF_PROF_MAX,
    CONF_PROF_NAME,
    CONF_PROF_PATTERN,
    CONF_PROF_SUB,
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
from .importer import import_available, legacy_options, legacy_subentries
from .recorder_client import RecorderClient, RecorderError

_TEXT = selector.TextSelector()
_SECRET = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


def _ent(*domains: str) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=list(domains)))


def _num(lo: int, hi: int) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=lo, max=hi, step=1, mode=selector.NumberSelectorMode.BOX)
    )


def _suggest(schema: vol.Schema, values: dict[str, Any]) -> vol.Schema:
    """Vorbelegung als 'suggested_value' (Felder lassen sich so wieder leeren)."""
    return vol.Schema(
        {
            (type(k)(k.schema, default=k.default, description={"suggested_value": values.get(k.schema)}) if k.schema in values else k): v
            for k, v in schema.schema.items()
        }
    )


SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_RECORDER_URL): _TEXT,
        vol.Required(CONF_RECORDER_KEY): _SECRET,
    }
)


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in user_input.items() if k != CONF_IMPORT and v not in (None, "")}


class CamRecorderProfileConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        can_import = import_available(self.hass)
        if user_input is not None:
            subentries: list[ConfigSubentryData] = []
            if can_import and user_input.get(CONF_IMPORT, True):
                # Laufzeit-Detail: HA uebernimmt 'subentry_id' aus diesen Daten, so bleiben die Cam-IDs erhalten
                subentries = [cast(ConfigSubentryData, item) for item in legacy_subentries(self.hass)]
            return self.async_create_entry(
                title="Cam Recorder Profile", data={}, options=_clean(user_input), subentries=subentries
            )
        schema = SETTINGS_SCHEMA
        suggested = {**DEFAULT_OPTIONS, **legacy_options(self.hass)}
        if can_import:
            schema = schema.extend({vol.Optional(CONF_IMPORT, default=True): selector.BooleanSelector()})
        return self.async_show_form(
            step_id="user",
            data_schema=_suggest(schema, suggested),
            description_placeholders={"anzahl": str(len(legacy_subentries(self.hass)) if can_import else 0)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CamRecorderProfileOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_CAM: CamSubentryFlow, SUBENTRY_PROFILE: ProfileSubentryFlow}


class CamRecorderProfileOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=_clean(user_input))
        current = {**DEFAULT_OPTIONS, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_suggest(SETTINGS_SCHEMA, current))


# ----------------------------------------------------------------------- Cams
class CamSubentryFlow(ConfigSubentryFlow):
    """Cam mit Kuerzel und Stream-Quelle anlegen / bearbeiten."""

    @staticmethod
    def _schema(with_name: bool) -> vol.Schema:
        fields: dict[Any, Any] = {}
        if with_name:
            fields[vol.Required(CONF_CAM_NAME)] = _TEXT
        fields[vol.Required(CONF_CAM_KUERZEL)] = _TEXT
        fields[vol.Optional(CONF_CAM_RECORD, default=True)] = selector.BooleanSelector()
        fields[vol.Optional(CONF_CAM_STREAM)] = _ent("camera")
        fields[vol.Optional(CONF_CAM_RTSP)] = _SECRET
        return vol.Schema(fields)

    @staticmethod
    def _recorder_fields(user_input: dict[str, Any]) -> dict[str, Any]:
        return {
            CONF_CAM_KUERZEL: user_input[CONF_CAM_KUERZEL].strip(),
            CONF_CAM_RECORD: bool(user_input.get(CONF_CAM_RECORD, True)),
            CONF_CAM_STREAM: user_input.get(CONF_CAM_STREAM, "") or "",
            CONF_CAM_RTSP: (user_input.get(CONF_CAM_RTSP, "") or "").strip(),
        }

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_CAM_NAME].strip()
            taken = {
                logic.norm(s.data[CONF_CAM_NAME])
                for s in self._get_entry().subentries.values()
                if s.subentry_type == SUBENTRY_CAM
            }
            if not name or logic.norm(name) in taken:
                errors[CONF_CAM_NAME] = "already_configured"
            elif not user_input[CONF_CAM_KUERZEL].strip():
                errors[CONF_CAM_KUERZEL] = "kuerzel_required"
            else:
                data = {CONF_CAM_NAME: name, **self._recorder_fields(user_input)}
                return self.async_create_entry(title=name, data=data, unique_id=logic.norm(name))
        return self.async_show_form(
            step_id="user", data_schema=_suggest(self._schema(True), user_input or {}), errors=errors
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_CAM_KUERZEL].strip():
                errors[CONF_CAM_KUERZEL] = "kuerzel_required"
            else:
                data = {**sub.data, **self._recorder_fields(user_input)}
                return self.async_update_and_abort(self._get_entry(), sub, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_suggest(self._schema(False), user_input or dict(sub.data)),
            errors=errors,
        )


# ------------------------------------------------------------------- Profile
def _folder_select(options: list[str]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=o, label=o) for o in options],
            custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


class ProfileSubentryFlow(ConfigSubentryFlow):
    """Aufnahme-Profil: wohin, welche Cams, welcher Ausloeser (Schritt 1 Hauptordner, Schritt 2 Unterordner)."""

    _pending: dict[str, Any]
    _own: str | None = None

    async def _dirs(self, parts: list[str]) -> list[str]:
        """Ordner aus dem Recorder (leer, wenn er nicht erreichbar ist - Eingabe von Hand bleibt moeglich)."""
        opts = self._get_entry().options
        url, key = opts.get(CONF_RECORDER_URL), opts.get(CONF_RECORDER_KEY)
        if not url or not key:
            return []
        try:
            return await RecorderClient(async_get_clientsession(self.hass), url, key).list_dirs(parts)
        except RecorderError:
            return []

    def _schema(self, main_options: list[str]) -> vol.Schema:
        cams = [
            selector.SelectOptionDict(value=sid, label=s.data[CONF_CAM_NAME])
            for sid, s in sorted(self._get_entry().subentries.items(), key=lambda kv: logic.norm(kv[1].data.get(CONF_CAM_NAME, "")))
            if s.subentry_type == SUBENTRY_CAM
        ]
        return vol.Schema(
            {
                vol.Required(CONF_PROF_NAME): _TEXT,
                vol.Required(CONF_PROF_MAIN): _folder_select(main_options),
                vol.Required(CONF_PROF_CAMS): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=cams, multiple=True, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional(CONF_PROF_PATTERN, default=DEFAULT_PATTERN): _TEXT,
                vol.Optional(CONF_PROF_TRIGGERS): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor", "switch", "input_boolean", "sensor"], multiple=True
                    )
                ),
                vol.Optional(CONF_PROF_AFTER): _num(0, 3600),
                vol.Optional(CONF_PROF_MAX): _num(0, 1440),
                vol.Optional(CONF_PROF_FROM): selector.TimeSelector(),
                vol.Optional(CONF_PROF_TO): selector.TimeSelector(),
                vol.Optional(CONF_PROF_SUN): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="", label="egal"),
                            selector.SelectOptionDict(value="tag", label="nur bei Tag (Sonne über dem Horizont)"),
                            selector.SelectOptionDict(value="nacht", label="nur bei Nacht (Sonne unter dem Horizont)"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

    @staticmethod
    def _data(user_input: dict[str, Any]) -> dict[str, Any]:
        main = logic.split_path(user_input.get(CONF_PROF_MAIN, ""))
        return {
            CONF_PROF_NAME: user_input[CONF_PROF_NAME].strip(),
            CONF_PROF_FOLDER: "/".join(main),
            CONF_PROF_CAMS: list(user_input.get(CONF_PROF_CAMS) or []),
            CONF_PROF_PATTERN: (user_input.get(CONF_PROF_PATTERN) or DEFAULT_PATTERN).strip(),
            CONF_PROF_TRIGGERS: list(user_input.get(CONF_PROF_TRIGGERS) or []),
            CONF_PROF_AFTER: int(user_input.get(CONF_PROF_AFTER) or 0),
            CONF_PROF_MAX: int(user_input.get(CONF_PROF_MAX) or 0),
            CONF_PROF_FROM: user_input.get(CONF_PROF_FROM) or "",
            CONF_PROF_TO: user_input.get(CONF_PROF_TO) or "",
            CONF_PROF_SUN: user_input.get(CONF_PROF_SUN) or "",
        }

    def _errors(self, data: dict[str, Any], own: str | None) -> dict[str, str]:
        errors: dict[str, str] = {}
        taken = {
            logic.norm(s.data[CONF_PROF_NAME])
            for sid, s in self._get_entry().subentries.items()
            if s.subentry_type == SUBENTRY_PROFILE and sid != own
        }
        if not data[CONF_PROF_NAME] or logic.norm(data[CONF_PROF_NAME]) in taken:
            errors[CONF_PROF_NAME] = "already_configured"
        if not data[CONF_PROF_FOLDER]:
            errors[CONF_PROF_MAIN] = "folder_required"
        if not data[CONF_PROF_CAMS]:
            errors[CONF_PROF_CAMS] = "cams_required"
        if bool(data[CONF_PROF_FROM]) != bool(data[CONF_PROF_TO]):
            errors[CONF_PROF_TO] = "time_both"
        return errors

    async def _step_one(self, step_id: str, user_input: dict[str, Any] | None, current: dict[str, Any]) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = self._data(user_input)
            errors = self._errors(data, self._own)
            if not errors:
                self._pending = data
                return await self.async_step_unterordner()
        main_options = await self._dirs([])
        return self.async_show_form(
            step_id=step_id, data_schema=_suggest(self._schema(main_options), user_input or current), errors=errors
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        self._own = None
        return await self._step_one("user", user_input, {})

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        self._own = sub.subentry_id
        parts = logic.split_path(sub.data.get(CONF_PROF_FOLDER, ""))
        current = {**sub.data, CONF_PROF_MAIN: parts[0] if parts else ""}
        return await self._step_one("reconfigure", user_input, current)

    async def async_step_unterordner(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        main = logic.split_path(self._pending[CONF_PROF_FOLDER])
        if user_input is not None:
            sub = logic.split_path(user_input.get(CONF_PROF_SUB, ""))
            data = {**self._pending, CONF_PROF_FOLDER: "/".join([*main, *sub])}
            if self._own is None:
                return self.async_create_entry(title=data[CONF_PROF_NAME], data=data, unique_id=logic.norm(data[CONF_PROF_NAME]))
            return self.async_update_and_abort(
                self._get_entry(), self._get_reconfigure_subentry(), title=data[CONF_PROF_NAME], data=data
            )
        existing = logic.split_path(self._get_reconfigure_subentry().data.get(CONF_PROF_FOLDER, "")) if self._own else []
        suggested = "/".join(existing[1:]) if existing[:1] == main[:1] else ""
        schema = vol.Schema({vol.Optional(CONF_PROF_SUB): _folder_select(await self._dirs(main))})
        return self.async_show_form(
            step_id="unterordner",
            data_schema=_suggest(schema, {CONF_PROF_SUB: suggested}),
            description_placeholders={"hauptordner": "/".join(main)},
        )
