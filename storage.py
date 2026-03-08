"""Storage handler for ProtoConfig."""
import logging
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.devices"


class DeviceStorage:
    """Handle storage of device configurations."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: Dict[str, Any] = {"devices": []}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data is not None:
            self._data = data

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    async def async_add_device(self, device_config: Dict[str, Any]) -> str:
        device_id = device_config.get("id")
        if not device_id:
            device_id = device_config["name"].lower().replace(" ", "_")
            counter = 1
            original_id = device_id
            while any(d["id"] == device_id for d in self._data["devices"]):
                device_id = f"{original_id}_{counter}"
                counter += 1
            device_config["id"] = device_id
        self._data["devices"].append(device_config)
        await self.async_save()
        return device_id

    async def async_update_device(self, device_id: str, device_config: Dict[str, Any]) -> bool:
        for i, device in enumerate(self._data["devices"]):
            if device["id"] == device_id:
                device_config["id"] = device_id
                self._data["devices"][i] = device_config
                await self.async_save()
                return True
        return False

    async def async_remove_device(self, device_id: str) -> bool:
        original_count = len(self._data["devices"])
        self._data["devices"] = [d for d in self._data["devices"] if d["id"] != device_id]
        if len(self._data["devices"]) < original_count:
            await self.async_save()
            return True
        return False

    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        for device in self._data["devices"]:
            if device["id"] == device_id:
                return device
        return None

    def get_all_devices(self) -> List[Dict[str, Any]]:
        return self._data["devices"]