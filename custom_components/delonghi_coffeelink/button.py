"""Buttons: one per learned drink, plus stop and 'learn recipes'."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CoffeeConfigEntry
from .api import protocol as p
from .coordinator import CoffeeCoordinator
from .entity import CoffeeEntity


async def async_setup_entry(hass: HomeAssistant, entry: CoffeeConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    added: set[int] = set(coordinator.recipes)
    async_add_entities(
        [StopButton(coordinator, "stop"), LearnButton(coordinator, "learn_recipes")]
        + [BrewButton(coordinator, r) for r in coordinator.recipes.values()]
    )

    @callback
    def _new(recipes: list[p.Recipe]) -> None:
        fresh = [r for r in recipes if r.beverage_id not in added]
        added.update(r.beverage_id for r in fresh)
        if fresh:
            async_add_entities([BrewButton(coordinator, r) for r in fresh])

    coordinator.add_recipe_listener(_new)


class BrewButton(CoffeeEntity, ButtonEntity):
    _attr_icon = "mdi:coffee"

    def __init__(self, coordinator: CoffeeCoordinator, recipe: p.Recipe) -> None:
        super().__init__(coordinator, f"brew_{recipe.beverage_id}")
        self.beverage_id = recipe.beverage_id
        self._attr_name = recipe.name

    async def async_press(self) -> None:
        recipe = self.coordinator.recipes[self.beverage_id]
        m = self.monitor
        if m is None or m.status != 7 or m.is_busy:
            raise HomeAssistantError(
                f"Machine not ready to brew (status {m.status_name if m else 'unknown'}"
                f"{', busy' if m and m.is_busy else ''})"
            )
        await self.coordinator.async_command(self.coordinator.machine.brew, recipe)
        self.coordinator.last_started = recipe


class StopButton(CoffeeEntity, ButtonEntity):
    _attr_translation_key = "stop"
    _attr_icon = "mdi:stop"

    async def async_press(self) -> None:
        recipe = self.coordinator.last_started
        if recipe is None or not recipe.stop:
            raise HomeAssistantError("Can only stop a drink started from Home Assistant")
        await self.coordinator.async_command(self.coordinator.machine.stop, recipe)


class LearnButton(CoffeeEntity, ButtonEntity):
    _attr_translation_key = "learn_recipes"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:school"

    async def async_press(self) -> None:
        self.coordinator.request_learn()
        await self.coordinator.async_request_refresh()
