"""De'Longhi Coffee Link (Ayla cloud) integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api.cloud import AuthError, AylaClient, CloudError, Machine, Tokens
from .const import CONF_ACCESS_TOKEN, CONF_DSN, CONF_EXPIRES_AT, CONF_REFRESH_TOKEN
from .coordinator import CoffeeCoordinator

PLATFORMS = [Platform.SWITCH, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

type CoffeeConfigEntry = ConfigEntry[CoffeeCoordinator]


def _make_client(hass: HomeAssistant, entry: ConfigEntry) -> AylaClient:
    def persist(tokens: Tokens) -> None:
        # Called from executor threads; the rotated refresh token must be saved.
        def _update() -> None:
            hass.config_entries.async_update_entry(entry, data={
                **entry.data,
                CONF_REFRESH_TOKEN: tokens.refresh_token,
                CONF_ACCESS_TOKEN: tokens.access_token,
                CONF_EXPIRES_AT: tokens.expires_at,
            })
        hass.loop.call_soon_threadsafe(_update)

    return AylaClient(
        Tokens(entry.data.get(CONF_REFRESH_TOKEN), entry.data.get(CONF_ACCESS_TOKEN),
               entry.data.get(CONF_EXPIRES_AT, 0.0)),
        on_tokens=persist,
        email=entry.data.get(CONF_EMAIL),
        password=entry.data.get(CONF_PASSWORD),
    )


async def async_setup_entry(hass: HomeAssistant, entry: CoffeeConfigEntry) -> bool:
    machine = Machine(_make_client(hass, entry), entry.data[CONF_DSN])
    try:
        info = await hass.async_add_executor_job(machine.info)
    except AuthError as e:
        raise ConfigEntryAuthFailed(str(e)) from e
    except CloudError as e:
        raise ConfigEntryNotReady(str(e)) from e

    coordinator = CoffeeCoordinator(hass, entry, machine, info)
    await coordinator.async_load_recipes()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CoffeeConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
