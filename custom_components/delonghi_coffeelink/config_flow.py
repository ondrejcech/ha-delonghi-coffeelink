"""Config flow: log in with the De'Longhi Coffee Link app account."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from .api.auth import InvalidCredentials, LoginError, login
from .api.cloud import AuthError, AylaClient, CloudError, Tokens
from .const import CONF_DSN, CONF_REFRESH_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

CREDS_SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})


def _login_and_list(email: str, password: str) -> tuple[str, list[dict]]:
    refresh = login(email, password)
    holder: dict[str, str] = {}
    client = AylaClient(Tokens(refresh), on_tokens=lambda t: holder.update(rt=t.refresh_token or ""))
    devices = client.devices()
    # The listing used (and rotated) the token; keep the newest one.
    return holder.get("rt", refresh), devices


class CoffeeLinkConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._email = ""
        self._password = ""
        self._refresh = ""
        self._devices: list[dict] = []

    async def _try_login(self, user_input: dict[str, Any]) -> str | None:
        self._email, self._password = user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
        try:
            self._refresh, self._devices = await self.hass.async_add_executor_job(
                _login_and_list, self._email, self._password
            )
        except (InvalidCredentials, AuthError) as e:
            _LOGGER.warning("De'Longhi login failed: %s", e)
            return "invalid_auth"
        except (LoginError, CloudError, OSError) as e:
            _LOGGER.warning("De'Longhi cloud unreachable: %s", e)
            return "cannot_connect"
        if not self._devices:
            return "no_devices"
        return None

    def _entry_data(self, dsn: str) -> dict[str, Any]:
        return {CONF_EMAIL: self._email, CONF_PASSWORD: self._password,
                CONF_REFRESH_TOKEN: self._refresh, CONF_DSN: dsn}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not (err := await self._try_login(user_input)):
                if len(self._devices) == 1:
                    return await self._create(self._devices[0])
                return await self.async_step_device()
            errors["base"] = err
        return self.async_show_form(step_id="user", data_schema=CREDS_SCHEMA, errors=errors)

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            dev = next(d for d in self._devices if d["dsn"] == user_input[CONF_DSN])
            return await self._create(dev)
        options = {d["dsn"]: f"{d.get('product_name') or d['dsn']} ({d.get('oem_model')})" for d in self._devices}
        return self.async_show_form(step_id="device", data_schema=vol.Schema({vol.Required(CONF_DSN): vol.In(options)}))

    async def _create(self, dev: dict) -> ConfigFlowResult:
        await self.async_set_unique_id(dev["dsn"])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=f"De'Longhi {dev.get('oem_model') or dev['dsn']}",
                                       data=self._entry_data(dev["dsn"]))

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            err = await self._try_login(user_input)
            if not err and not any(d.get("dsn") == entry.data[CONF_DSN] for d in self._devices):
                err = "wrong_account"
            if not err:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, **self._entry_data(entry.data[CONF_DSN]),
                                 "access_token": None, "expires_at": 0.0},
                )
            errors["base"] = err
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(CREDS_SCHEMA, {CONF_EMAIL: entry.data.get(CONF_EMAIL)}),
            errors=errors,
        )
