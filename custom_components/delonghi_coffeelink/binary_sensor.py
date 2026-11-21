"""Binary sensors: busy + maintenance alerts."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass, BinarySensorEntity, BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CoffeeConfigEntry
from .entity import CoffeeEntity


@dataclass(frozen=True, kw_only=True)
class CoffeeBinaryDescription(BinarySensorEntityDescription):
    attr: str


BINARY_SENSORS = (
    CoffeeBinaryDescription(key="busy", translation_key="busy", device_class=BinarySensorDeviceClass.RUNNING,
                            attr="is_busy"),
    CoffeeBinaryDescription(key="water_tank_empty", translation_key="water_tank_empty",
                            device_class=BinarySensorDeviceClass.PROBLEM, attr="water_tank_empty"),
    CoffeeBinaryDescription(key="water_tank_open", translation_key="water_tank_open",
                            device_class=BinarySensorDeviceClass.PROBLEM, attr="water_tank_open"),
    CoffeeBinaryDescription(key="waste_container_full", translation_key="waste_container_full",
                            device_class=BinarySensorDeviceClass.PROBLEM, attr="waste_container_full"),
    CoffeeBinaryDescription(key="waste_container_missing", translation_key="waste_container_missing",
                            device_class=BinarySensorDeviceClass.PROBLEM, attr="waste_container_missing"),
)


async def async_setup_entry(hass: HomeAssistant, entry: CoffeeConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(CoffeeBinarySensor(entry.runtime_data, d) for d in BINARY_SENSORS)


class CoffeeBinarySensor(CoffeeEntity, BinarySensorEntity):
    entity_description: CoffeeBinaryDescription

    def __init__(self, coordinator, description: CoffeeBinaryDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        m = self.monitor
        return getattr(m, self.entity_description.attr) if m else None
