"""Base entity."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CoffeeCoordinator


class CoffeeEntity(CoordinatorEntity[CoffeeCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: CoffeeCoordinator, key: str) -> None:
        super().__init__(coordinator)
        dsn = coordinator.machine.dsn
        info = coordinator.info
        self._attr_unique_id = f"{dsn}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dsn)},
            manufacturer="De'Longhi",
            model=info.get("oem_model") or "Coffee Link machine",
            sw_version=info.get("firmware"),
            serial_number=info.get("serial"),
            name="Coffee Machine",
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None and self.coordinator.data.online

    @property
    def monitor(self):
        return self.coordinator.data.state.monitor if self.coordinator.data else None
