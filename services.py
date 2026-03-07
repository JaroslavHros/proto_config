"""HA Services for Heat Pump Configurator."""
import json
import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_RELOAD = "reload"
SERVICE_EXPORT = "export"
SERVICE_IMPORT = "import"

SCHEMA_RELOAD = vol.Schema({
    vol.Optional("device_id"): str,
})

SCHEMA_EXPORT = vol.Schema({
    vol.Required("device_id"): str,
    vol.Optional("output_path"): str,
})

SCHEMA_IMPORT = vol.Schema({
    vol.Required("config_path"): str,
})


def _active_entry_ids(hass) -> set:
    """Return entry_ids of currently loaded (not deleted) entries."""
    return set(hass.data.get(DOMAIN, {}).get("entries", {}).keys())


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register all integration services."""

    async def handle_reload(call: ServiceCall) -> None:
        """Regenerate YAML only for active (non-deleted) devices."""
        from . import _generate_config

        storage = hass.data[DOMAIN].get("storage")
        if not storage:
            _LOGGER.error("Storage not initialized")
            return

        # Only regenerate devices that are still active in HA
        active_ids = _active_entry_ids(hass)

        requested_id = call.data.get("device_id")

        if requested_id:
            device = storage.get_device(requested_id)
            devices = [device] if device else []
        else:
            # All active devices only — never ghost/deleted ones
            devices = [
                d for d in storage.get_all_devices()
                if d.get("id") in active_ids
            ]

        devices = [d for d in devices if d]

        for device in devices:
            file_id = device.get("file_id") or device.get("name", "device").lower().replace(" ", "_")
            try:
                await _generate_config(hass, device, file_id)
                _LOGGER.info("Regenerated YAML for %s", file_id)
            except Exception as e:
                _LOGGER.error("Reload failed for %s: %s", file_id, e)

        await hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": "Heat Pump Configurator",
                "message": f"Reload complete for {len(devices)} device(s).",
                "notification_id": "heatpump_reload",
            },
        )

    async def handle_export(call: ServiceCall) -> None:
        """Export device configuration to JSON."""
        storage = hass.data[DOMAIN].get("storage")
        if not storage:
            return

        device_id = call.data["device_id"]
        device = storage.get_device(device_id)
        if not device:
            _LOGGER.error("Device %s not found for export", device_id)
            return

        file_id = device.get("file_id", device_id)
        output_path = call.data.get("output_path") or hass.config.path(f"heatpump_export_{file_id}.json")
        export_data = {
            "heatpump_configurator_export": True,
            "version": "0.2.0",
            "device": device,
        }

        def _write():
            Path(output_path).write_text(
                json.dumps(export_data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )

        await hass.async_add_executor_job(_write)
        _LOGGER.info("Exported device %s to %s", file_id, output_path)

        await hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": "Heat Pump Configurator - Export",
                "message": f"Configuration exported to:\n`{output_path}`",
                "notification_id": f"heatpump_export_{file_id}",
            },
        )

    async def handle_import(call: ServiceCall) -> None:
        """Import device configuration from JSON."""
        config_path = call.data["config_path"]

        def _read():
            return Path(config_path).read_text(encoding="utf-8")

        try:
            raw = await hass.async_add_executor_job(_read)
            data = json.loads(raw)
        except Exception as e:
            _LOGGER.error("Failed to read import file %s: %s", config_path, e)
            return

        if not data.get("heatpump_configurator_export"):
            _LOGGER.error("File %s is not a valid Heat Pump Configurator export", config_path)
            return

        device = data.get("device", {})
        if not device:
            return

        storage = hass.data[DOMAIN].get("storage")
        if not storage:
            return

        device.pop("id", None)
        new_id = await storage.async_add_device(device)
        _LOGGER.info("Imported device as %s", new_id)

        await hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": "Heat Pump Configurator - Import",
                "message": (
                    f"Device imported as `{new_id}`.\n\n"
                    f"Go to **Settings → Devices & Services → Heat Pump Configurator** "
                    f"to add it as an integration entry."
                ),
                "notification_id": f"heatpump_import_{new_id}",
            },
        )

    hass.services.async_register(DOMAIN, SERVICE_RELOAD, handle_reload, schema=SCHEMA_RELOAD)
    hass.services.async_register(DOMAIN, SERVICE_EXPORT, handle_export, schema=SCHEMA_EXPORT)
    hass.services.async_register(DOMAIN, SERVICE_IMPORT, handle_import, schema=SCHEMA_IMPORT)
    _LOGGER.debug("Registered services: reload, export, import")