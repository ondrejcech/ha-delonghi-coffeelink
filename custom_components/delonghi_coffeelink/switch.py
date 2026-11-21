"""Power switch (wake up / standby)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CoffeeConfigEntry
from .entity import CoffeeEntity


async def async_setup_entry(hass: HomeAssistant, entry: CoffeeConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([PowerSwitch(entry.runtime_data, "power")])


class PowerSwitch(CoffeeEntity, SwitchEntity):
    _attr_translation_key = "power"

    @property
    def is_on(self) -> bool | None:
        m = self.monitor
        return m.is_on if m else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(self.coordinator.machine.wake)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(self.coordinator.machine.standby)
