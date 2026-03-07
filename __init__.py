"""Heat Pump Configurator — main integration module."""
import logging
import re
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, CONN_MODBUS_TCP, CONN_MODBUS_RTU, CONN_ESPHOME
from .generators import ModbusYAMLGenerator, ESPHomeYAMLGenerator
from .storage import DeviceStorage
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


def _file_id_from_name(name: str) -> str:
    """'My TC 1' -> 'my_tc_1'  (safe filename)."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower().strip()).strip("_")
    return slug or "heatpump"


def _yaml_path(hass, device_config: dict) -> Path | None:
    file_id = device_config.get("file_id", "")
    if not file_id:
        return None
    conn = device_config.get("connection_type")
    if conn in (CONN_MODBUS_TCP, CONN_MODBUS_RTU):
        return Path(hass.config.path("modbus")) / f"{file_id}.yaml"
    if conn == CONN_ESPHOME:
        return Path(hass.config.path("esphome")) / f"{file_id}.yaml"
    return None


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Called on every HA start AND after options save (via reload).

    YAML generation happens ONLY when the config/options actually changed
    (flagged by 'needs_generate' in entry.options), NOT on every restart.
    """
    _LOGGER.info("Setting up: %s", entry.title)
    hass.data.setdefault(DOMAIN, {})

    # Shared storage — init once per HA session
    if "storage" not in hass.data[DOMAIN]:
        storage = DeviceStorage(hass)
        await storage.async_load()
        hass.data[DOMAIN]["storage"] = storage

    if "services_registered" not in hass.data[DOMAIN]:
        await async_setup_services(hass)
        hass.data[DOMAIN]["services_registered"] = True

    storage = hass.data[DOMAIN]["storage"]
    device_config = {**entry.data, **entry.options}

    # Stable internal key, human-readable filename
    storage_id = entry.entry_id
    file_id = _file_id_from_name(device_config.get("name", "heatpump"))
    device_config["id"] = storage_id
    device_config["file_id"] = file_id

    # Sync to DeviceStorage (for services like export/reload)
    if storage.get_device(storage_id):
        await storage.async_update_device(storage_id, dict(device_config))
    else:
        await storage.async_add_device(dict(device_config))

    # Generate YAML only when flagged — avoids recreating deleted files on restart
    needs_generate = device_config.pop("needs_generate", False)
    if needs_generate:
        # Clear the flag from entry.data/options so it doesn't persist across restarts
        clean_data = {k: v for k, v in entry.data.items() if k != "needs_generate"}
        clean_options = {k: v for k, v in entry.options.items() if k != "needs_generate"}
        hass.config_entries.async_update_entry(entry, data=clean_data, options=clean_options)

        stored = storage.get_device(storage_id)
        try:
            await _generate_config(hass, stored, file_id)
        except Exception as err:
            _LOGGER.error("Config generation failed for %s: %s", entry.title, err)
            raise ConfigEntryNotReady from err

    hass.data[DOMAIN].setdefault("entries", {})[entry.entry_id] = storage_id
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options saved — set flag then reload so generation runs exactly once."""
    # Merge needs_generate flag into options
    new_options = {**entry.options, "needs_generate": True}
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Called on reload AND remove — do NOT delete files here."""
    hass.data[DOMAIN].get("entries", {}).pop(entry.entry_id, None)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Called ONLY when user deletes the integration entry."""
    _LOGGER.info("Removing: %s", entry.title)

    storage: DeviceStorage | None = hass.data.get(DOMAIN, {}).get("storage")
    if not storage:
        storage = DeviceStorage(hass)
        await storage.async_load()

    device = storage.get_device(entry.entry_id)
    if device:
        yaml_file = _yaml_path(hass, device)
        if yaml_file and yaml_file.exists():
            await hass.async_add_executor_job(yaml_file.unlink)
            _LOGGER.info("Deleted YAML: %s", yaml_file)
        await storage.async_remove_device(entry.entry_id)


# ── YAML generation ───────────────────────────────────────────────────────────

async def _generate_config(hass, device_config: dict, file_id: str) -> None:
    conn = device_config.get("connection_type")
    if conn in (CONN_MODBUS_TCP, CONN_MODBUS_RTU):
        await _generate_modbus(hass, device_config, file_id)
    elif conn == CONN_ESPHOME:
        await _generate_esphome(hass, device_config, file_id)
    else:
        _LOGGER.debug("No generator for: %s", conn)


async def _generate_modbus(hass, device_config: dict, file_id: str) -> None:
    modbus_dir = Path(hass.config.path("modbus"))
    modbus_dir.mkdir(exist_ok=True)
    yaml_file = modbus_dir / f"{file_id}.yaml"

    if device_config.get("passthrough_type") == "ha_modbus_sensors":
        await _write_ha_modbus_sensors(hass, device_config, yaml_file)
        msg = (
            f"Vygenerovaný Modbus sensors list: `{yaml_file}`\n\n"
            f"Pridaj do `configuration.yaml`:\n"
            f"```yaml\nmodbus:\n  - name: {device_config.get('name', 'tc')}\n"
            f"    type: tcp\n"
            f"    host: {device_config.get('connection_params', {}).get('host', '192.168.x.x')}\n"
            f"    port: {device_config.get('connection_params', {}).get('port', 502)}\n"
            f"    sensors: !include_dir_merge_list modbus/\n```\n\n"
            f"Potom reštartuj HA alebo reload Modbus."
        )
    else:
        cfg = ModbusYAMLGenerator.generate(device_config)
        await ModbusYAMLGenerator.write_to_file(cfg, yaml_file)
        msg = (
            f"Vygenerovaný Modbus config: `{yaml_file}`\n\n"
            f"Pridaj do `configuration.yaml`:\n"
            f"```yaml\nmodbus: !include_dir_merge_list modbus/\n```\n\n"
            f"Potom reštartuj HA alebo reload Modbus."
        )

    _LOGGER.info("Generated Modbus YAML: %s", yaml_file)
    await hass.services.async_call("persistent_notification", "create", {
        "title": "Heat Pump Configurator — Modbus",
        "message": msg,
        "notification_id": f"heatpump_modbus_{file_id}",
    })


async def _write_ha_modbus_sensors(hass, device_config: dict, yaml_file: Path) -> None:
    import yaml as _yaml
    slave = device_config.get("connection_params", {}).get("slave", 1)
    items = []
    for reg in device_config.get("registers", []):
        addr = reg.get("register", 0)
        item = {
            "name": reg.get("friendly_name") or reg.get("name", ""),
            "slave": slave,
            "address": f"0x{addr:04X}" if isinstance(addr, int) else str(addr),
            "data_type": reg.get("data_type", "uint16"),
        }
        for src, dst in [
            ("unit", "unit_of_measurement"), ("device_class", "device_class"),
            ("state_class", "state_class"), ("scale", "scale"),
            ("precision", "precision"), ("scan_interval", "scan_interval"),
        ]:
            if reg.get(src) is not None:
                item[dst] = reg[src]
        items.append(item)

    def _write():
        yaml_file.write_text(
            _yaml.dump(items, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
    await hass.async_add_executor_job(_write)


async def _generate_esphome(hass, device_config: dict, file_id: str) -> None:
    esphome_dir = Path(hass.config.path("esphome"))
    esphome_dir.mkdir(exist_ok=True)
    yaml_file = esphome_dir / f"{file_id}.yaml"

    if device_config.get("passthrough") and device_config.get("passthrough_yaml"):
        raw = device_config["passthrough_yaml"]
        await hass.async_add_executor_job(
            lambda: yaml_file.write_text(raw, encoding="utf-8")
        )
        _LOGGER.info("Wrote passthrough ESPHome YAML: %s", yaml_file)
    else:
        cfg = ESPHomeYAMLGenerator.generate(device_config)
        await ESPHomeYAMLGenerator.write_to_file(cfg, yaml_file)
        _LOGGER.info("Generated ESPHome YAML: %s", yaml_file)

    await hass.services.async_call("persistent_notification", "create", {
        "title": "Heat Pump Configurator — ESPHome",
        "message": (
            f"Vygenerovaný ESPHome config: `{yaml_file}`\n\n"
            f"Ďalšie kroky:\n"
            f"1. Skopíruj do ESPHome adresára\n"
            f"2. Skompiluj a nahraj na ESP\n"
            f"3. Zariadenie sa objaví v HA"
        ),
        "notification_id": f"heatpump_esphome_{file_id}",
    })