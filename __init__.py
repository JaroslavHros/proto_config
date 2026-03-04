"""Heat Pump Configurator v0.2 — main integration module."""
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, CONN_MODBUS_TCP, CONN_MODBUS_RTU, CONN_ESPHOME
from .generators import ModbusYAMLGenerator, ESPHomeYAMLGenerator
from .storage import DeviceStorage
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Global setup — runs once."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry (one per device)."""
    _LOGGER.info("Setting up Heat Pump Configurator: %s", entry.title)

    hass.data.setdefault(DOMAIN, {})

    # Shared storage (initialised once)
    if "storage" not in hass.data[DOMAIN]:
        storage = DeviceStorage(hass)
        await storage.async_load()
        hass.data[DOMAIN]["storage"] = storage

    # Register services once
    if "services_registered" not in hass.data[DOMAIN]:
        await async_setup_services(hass)
        hass.data[DOMAIN]["services_registered"] = True

    storage = hass.data[DOMAIN]["storage"]

    # Merge entry data with options (options override data)
    device_config = {**entry.data, **entry.options}

    # Persist to storage
    device_id = await storage.async_add_device(dict(device_config))
    stored_device = storage.get_device(device_id)

    # Generate protocol YAML
    try:
        await _generate_config(hass, stored_device, device_id)
    except Exception as err:
        _LOGGER.error("Config generation failed for %s: %s", device_id, err)
        raise ConfigEntryNotReady from err

    hass.data[DOMAIN].setdefault("entries", {})[entry.entry_id] = device_id

    # Register options update listener so edits trigger regeneration
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Called when the user saves changes in OptionsFlow."""
    _LOGGER.info("Options updated for %s — reloading entry", entry.title)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove a config entry and its generated YAML."""
    _LOGGER.info("Unloading Heat Pump Configurator: %s", entry.title)

    device_id = hass.data[DOMAIN].get("entries", {}).pop(entry.entry_id, None)
    if device_id:
        storage = hass.data[DOMAIN]["storage"]
        device = storage.get_device(device_id)

        await storage.async_remove_device(device_id)

        if device:
            conn_type = device.get("connection_type")
            if conn_type in (CONN_MODBUS_TCP, CONN_MODBUS_RTU):
                yaml_file = Path(hass.config.path("modbus")) / f"{device_id}.yaml"
            elif conn_type == CONN_ESPHOME:
                yaml_file = Path(hass.config.path("esphome")) / f"{device_id}.yaml"
            else:
                yaml_file = None

            if yaml_file and yaml_file.exists():
                yaml_file.unlink()
                _LOGGER.info("Removed YAML file: %s", yaml_file)

    return True


# ─────────────────────────────────────────────────────────────────────────────
# YAML generation helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _generate_config(hass: HomeAssistant, device_config: dict, device_id: str) -> None:
    conn_type = device_config.get("connection_type")

    if conn_type in (CONN_MODBUS_TCP, CONN_MODBUS_RTU):
        await _generate_modbus(hass, device_config, device_id)
    elif conn_type == CONN_ESPHOME:
        await _generate_esphome(hass, device_config, device_id)
    else:
        _LOGGER.debug("No YAML generator for connection type: %s", conn_type)


async def _generate_modbus(hass: HomeAssistant, device_config: dict, device_id: str) -> None:
    modbus_dir = Path(hass.config.path("modbus"))
    modbus_dir.mkdir(exist_ok=True)

    cfg = ModbusYAMLGenerator.generate(device_config)
    yaml_file = modbus_dir / f"{device_id}.yaml"
    await ModbusYAMLGenerator.write_to_file(cfg, yaml_file)
    _LOGGER.info("Generated Modbus YAML: %s", yaml_file)

    await hass.services.async_call(
        "persistent_notification", "create",
        {
            "title": "Heat Pump Configurator",
            "message": (
                f"Generated Modbus config: `{yaml_file}`\n\n"
                f"Add to `configuration.yaml`:\n"
                f"```yaml\nmodbus: !include_dir_merge_list modbus/\n```\n\n"
                f"Then restart HA or reload Modbus."
            ),
            "notification_id": f"heatpump_setup_{device_id}",
        },
    )


async def _generate_esphome(hass: HomeAssistant, device_config: dict, device_id: str) -> None:
    esphome_dir = Path(hass.config.path("esphome"))
    esphome_dir.mkdir(exist_ok=True)

    cfg = ESPHomeYAMLGenerator.generate(device_config)
    yaml_file = esphome_dir / f"{device_id}.yaml"
    await ESPHomeYAMLGenerator.write_to_file(cfg, yaml_file)
    _LOGGER.info("Generated ESPHome YAML: %s", yaml_file)

    await hass.services.async_call(
        "persistent_notification", "create",
        {
            "title": "Heat Pump Configurator — ESPHome",
            "message": (
                f"Generated ESPHome config: `{yaml_file}`\n\n"
                f"**Ďalšie kroky:**\n"
                f"1. Skopíruj súbor do ESPHome adresára\n"
                f"2. Vytvor `secrets.yaml` s WiFi prihlasovacími údajmi\n"
                f"3. Skompiluj a nahraj na ESP zariadenie\n"
                f"4. Zariadenie sa automaticky objaví v HA\n\n"
                f"Exportovať konfiguráciu: `heatpump_configurator.export`"
            ),
            "notification_id": f"heatpump_esphome_{device_id}",
        },
    )
