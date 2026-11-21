"""Sensors: status, progress, counters."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CoffeeConfigEntry
from .api.protocol import STATUS_NAMES
from .coordinator import CoffeeData
from .entity import CoffeeEntity


@dataclass(frozen=True, kw_only=True)
class CoffeeSensorDescription(SensorEntityDescription):
    value_fn: Callable[[CoffeeData], int | str | None]


def _mon(attr: str):
    return lambda d: getattr(d.state.monitor, attr) if d.state.monitor else None


def _cnt(key: str):
    return lambda d: d.counters.get(key)


SENSORS: tuple[CoffeeSensorDescription, ...] = (
    CoffeeSensorDescription(
        key="status", translation_key="status", device_class=SensorDeviceClass.ENUM,
        options=sorted(set(STATUS_NAMES.values()) | {"unknown"}),
        value_fn=lambda d: (d.state.monitor.status_name if d.state.monitor.status in STATUS_NAMES else "unknown")
        if d.state.monitor else None,
    ),
    CoffeeSensorDescription(key="progress", translation_key="progress", native_unit_of_measurement=PERCENTAGE,
                            value_fn=_mon("progress")),
    CoffeeSensorDescription(key="action", translation_key="action", entity_category=EntityCategory.DIAGNOSTIC,
                            value_fn=_mon("action")),
    CoffeeSensorDescription(key="total_beverages", translation_key="total_beverages",
                            state_class=SensorStateClass.TOTAL_INCREASING, value_fn=_cnt("d701_tot_bev_b")),
    CoffeeSensorDescription(key="espressos", translation_key="espressos",
                            state_class=SensorStateClass.TOTAL_INCREASING, value_fn=_cnt("d705_tot_id1_espr")),
    CoffeeSensorDescription(key="coffees", translation_key="coffees",
                            state_class=SensorStateClass.TOTAL_INCREASING, value_fn=_cnt("d706_tot_id2_coffee")),
    CoffeeSensorDescription(key="long_coffees", translation_key="long_coffees",
                            state_class=SensorStateClass.TOTAL_INCREASING, value_fn=_cnt("d707_tot_id3_long")),
    CoffeeSensorDescription(key="grounds", translation_key="grounds", state_class=SensorStateClass.MEASUREMENT,
                            value_fn=_cnt("d551_cnt_coffee_fondi")),
    CoffeeSensorDescription(key="descale_count", translation_key="descale_count",
                            entity_category=EntityCategory.DIAGNOSTIC,
                            state_class=SensorStateClass.TOTAL_INCREASING, value_fn=_cnt("d552_cnt_calc_tot")),
    CoffeeSensorDescription(key="water_hardness", translation_key="water_hardness",
                            entity_category=EntityCategory.DIAGNOSTIC, value_fn=_cnt("d556_water_hardness")),
)


async def async_setup_entry(hass: HomeAssistant, entry: CoffeeConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(CoffeeSensor(entry.runtime_data, desc) for desc in SENSORS)


class CoffeeSensor(CoffeeEntity, SensorEntity):
    entity_description: CoffeeSensorDescription

    def __init__(self, coordinator, description: CoffeeSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data) if self.coordinator.data else None
