"""Polling coordinator for a De'Longhi Coffee Link machine."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import protocol as p
from .api.cloud import AuthError, CloudError, Machine, MachineState
from .const import (
    COUNTERS_EVERY, DOMAIN, INTERVAL_BUSY, INTERVAL_IDLE, INTERVAL_STANDBY,
    LEARN_EVERY, ONLINE_EVERY, STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class CoffeeData:
    state: MachineState
    counters: dict[str, int] = field(default_factory=dict)
    online: bool = True


class CoffeeCoordinator(DataUpdateCoordinator[CoffeeData]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, machine: Machine, info: dict):
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=INTERVAL_IDLE)
        self.machine = machine
        self.info = info
        self.recipes: dict[int, p.Recipe] = {}
        self.last_started: p.Recipe | None = None
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.recipes")
        self._counters: dict[str, int] = {}
        self._online = True
        self._last_counters = 0.0
        self._last_online = 0.0
        self._last_learn = 0.0
        self._recipe_listeners: list = []
        self._fast_until = 0.0

    async def async_load_recipes(self) -> None:
        data = await self._store.async_load() or {}
        self.recipes = {int(k): p.Recipe(**v) for k, v in data.items()}

    def add_recipe_listener(self, cb) -> None:
        self._recipe_listeners.append(cb)

    def request_learn(self) -> None:
        self._last_learn = 0.0

    def _poll(self) -> tuple[CoffeeData, dict[int, p.Recipe] | None]:
        now = time.time()
        with_counters = now - self._last_counters > COUNTERS_EVERY
        with_online = now - self._last_online > ONLINE_EVERY
        st = self.machine.poll(with_counters=with_counters, with_online=with_online)
        if with_counters:
            self._counters = st.counters
            self._last_counters = now
        if with_online:
            self._online = st.online
            self._last_online = now
        if self._online:
            try:
                self.machine.keepalive(st.registered_app)
            except CloudError as e:
                _LOGGER.debug("keepalive failed: %s", e)
        learned = None
        if now - self._last_learn > LEARN_EVERY:
            self._last_learn = now
            try:
                learned = self.machine.learn_recipes()
            except CloudError as e:
                _LOGGER.debug("recipe learning failed: %s", e)
        return CoffeeData(state=st, counters=dict(self._counters), online=self._online), learned

    async def _async_update_data(self) -> CoffeeData:
        try:
            data, learned = await self.hass.async_add_executor_job(self._poll)
        except AuthError as e:
            raise ConfigEntryAuthFailed(str(e)) from e
        except CloudError as e:
            raise UpdateFailed(str(e)) from e

        if learned:
            new = {k: v for k, v in learned.items() if k not in self.recipes or self.recipes[k].start != v.start}
            if new:
                self.recipes.update(new)
                await self._store.async_save({str(k): vars(v) for k, v in self.recipes.items()})
                _LOGGER.info("Learned recipes: %s", ", ".join(r.name for r in new.values()))
                for cb in self._recipe_listeners:
                    cb(list(new.values()))

        m = data.state.monitor
        if time.monotonic() < self._fast_until or (m is not None and (m.is_busy or m.status in (1, 2))):
            # Just sent a command (the monitor may still show the old state), or in transition.
            self.update_interval = INTERVAL_BUSY
        elif m is not None and m.status == 0:
            self.update_interval = INTERVAL_STANDBY
        else:
            self.update_interval = INTERVAL_IDLE
        return data

    async def async_command(self, fn, *args) -> None:
        try:
            await self.hass.async_add_executor_job(fn, *args)
        except AuthError as e:
            # ConfigEntryAuthFailed only triggers reauth from setup/updates, not from actions.
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(f"De'Longhi authentication failed: {e}") from e
        except CloudError as e:
            raise HomeAssistantError(f"De'Longhi cloud command failed: {e}") from e
        self._fast_until = time.monotonic() + 60
        self.update_interval = INTERVAL_BUSY
        await self.async_request_refresh()
