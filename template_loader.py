"""External template loader for ProtoConfig.

Templates are loaded from:
  <HA config>/heatpump_templates/

Supported formats: JSON (.json) and YAML (.yaml / .yml)

REQUIRED: Every template file must contain the marker:
  "_heatpump_template": true

This prevents accidentally loading unrelated YAML/JSON files.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

_LOGGER = logging.getLogger(__name__)

TEMPLATES_DIR = "heatpump_templates"
TEMPLATE_MARKER = "_heatpump_template"


def get_templates_dir(hass_config_dir: str) -> Path:
    return Path(hass_config_dir) / TEMPLATES_DIR


def _ensure_templates_dir_sync(hass_config_dir: str) -> Path:
    """Create templates directory and example file. Runs in executor."""
    d = get_templates_dir(hass_config_dir)
    d.mkdir(exist_ok=True)

    readme = d / "README.md"
    if not readme.exists():
        readme.write_text(
            "# ProtoConfig — External Templates\n\n"
            "Umiestni sem JSON alebo YAML súbory so sablonami zariadeni.\n"
            "Kazdy subor musi obsahovat marker: \"_heatpump_template\": true\n\n"
            "Subory sa automaticky objavia v zozname sablon pri pridavani zariadenia.\n",
            encoding="utf-8",
        )

    example = d / "_example_template.json"
    if not example.exists():
        example.write_text(
            json.dumps(
                {
                    "_heatpump_template": True,
                    "_description": "Premenuj na moje_zariadenie.json a uprav.",
                    "name": "Moje TC",
                    "connection_type": "esphome",
                    "scan_interval": 5,
                    "connection_params": {
                        "platform": "ESP32",
                        "board": "esp32dev",
                        "tx_pin": "GPIO15",
                        "rx_pin": "GPIO14",
                        "baudrate": 9600,
                        "slave": 1,
                        "parity": "NONE",
                        "stop_bits": 1,
                    },
                    "registers": [
                        {
                            "name": "teplota_vody",
                            "friendly_name": "Teplota vody",
                            "register": "0x000E",
                            "register_type": "holding",
                            "data_type": "uint16",
                            "entity_type": "sensor",
                            "unit": "C",
                            "device_class": "temperature",
                            "state_class": "measurement",
                            "accuracy_decimals": 1,
                            "icon": "mdi:thermometer",
                            "custom_filters": "- multiply: 0.1",
                        }
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return d


async def ensure_templates_dir(hass) -> Path:
    """Async wrapper — runs file I/O in executor to avoid blocking event loop."""
    return await hass.async_add_executor_job(
        _ensure_templates_dir_sync, hass.config.config_dir
    )



def _load_yaml_esphome(text: str) -> Any:
    """
    Load YAML that may contain ESPHome-specific tags like !lambda, !secret, !include.
    These are treated as plain strings — the tag content is preserved as-is.
    """
    import yaml

    class _EspHomeLoader(yaml.SafeLoader):
        pass

    def _tag_constructor(loader, tag_suffix, node):
        """Return tagged scalar/sequence/mapping as plain Python value."""
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        elif isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        elif isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return None

    # Register handler for any unknown tag
    _EspHomeLoader.add_multi_constructor("", _tag_constructor)

    return yaml.load(text, Loader=_EspHomeLoader)



def _convert_ha_modbus_sensors(items: list, source_file: str) -> Optional[Dict[str, Any]]:
    """
    Convert a flat HA Modbus sensors list (used with !include) to our template format.
    Format: root is a list of dicts, each with address/slave/name/data_type etc.
    No connection params are stored — user fills those in the wizard.
    """
    registers = []
    slave = 1  # default, take from first item

    for item in items:
        if not isinstance(item, dict) or "address" not in item:
            continue

        slave = item.get("slave", slave)
        addr = item.get("address", 0)
        name_raw = item.get("name", f"reg_{addr}")

        # Generate internal ID from name
        import re
        reg_id = re.sub(r"[^a-z0-9_]", "_", name_raw.lower()).strip("_")
        reg_id = re.sub(r"_+", "_", reg_id)

        # Parse address but keep as int — generator will write as hex
        addr_int = addr if isinstance(addr, int) else _parse_register_address(str(addr))
        reg = {
            "name": reg_id,
            "friendly_name": name_raw,
            "register": addr_int,
            "register_type": "holding",
            "data_type": item.get("data_type", "uint16"),
            "entity_type": "sensor",
        }

        # Map HA Modbus fields to our fields
        if item.get("unit_of_measurement"):
            reg["unit"] = item["unit_of_measurement"]
        if item.get("device_class"):
            reg["device_class"] = item["device_class"]
        if item.get("state_class"):
            reg["state_class"] = item["state_class"]
        if item.get("scale") is not None:
            reg["scale"] = item["scale"]
        if item.get("precision") is not None:
            reg["precision"] = item["precision"]
        if item.get("scan_interval") is not None:
            reg["scan_interval"] = item["scan_interval"]

        registers.append(reg)

    if not registers:
        return None

    name = Path(source_file).stem.replace("_", " ").title()

    return {
        "name": name,
        "connection_type": "modbus_tcp",   # user will change this in wizard
        "scan_interval": registers[0].get("scan_interval", 10) if registers else 10,
        "connection_params": {
            "host": "192.168.1.100",       # placeholder — user changes in wizard
            "port": 502,
            "slave": slave,
        },
        "registers": registers,
        # Store original YAML for passthrough write
        "passthrough": True,
        "passthrough_type": "ha_modbus_sensors",
    }

def _load_templates_sync(hass_config_dir: str) -> Dict[str, Dict[str, Any]]:
    """
    Scan heatpump_templates/ and return {template_key: template_dict}.
    Only loads files that contain the marker: _heatpump_template: true
    Runs in executor thread — no blocking event loop.
    """
    d = get_templates_dir(hass_config_dir)

    if not d.exists():
        _LOGGER.debug("Templates dir does not exist: %s", d)
        return {}

    templates: Dict[str, Dict[str, Any]] = {}

    for f in sorted(d.iterdir()):
        if f.suffix.lower() not in (".json", ".yaml", ".yml"):
            continue
        if f.name.startswith("_"):
            continue

        try:
            if f.suffix.lower() == ".json":
                raw = json.loads(f.read_text(encoding="utf-8"))
            else:
                raw = _load_yaml_esphome(f.read_text(encoding="utf-8"))

            # Format 1: flat list of HA Modbus sensors (used with !include)
            if isinstance(raw, list):
                if raw and isinstance(raw[0], dict) and "address" in raw[0]:
                    tpl = _convert_ha_modbus_sensors(raw, f.name)
                else:
                    _LOGGER.debug("Skipping %s — list but not modbus sensors", f.name)
                    continue

            elif isinstance(raw, dict):
                # Format 2: native ESPHome YAML
                if raw.get("esphome") and (raw.get("sensor") or raw.get("select")):
                    raw_text = f.read_text(encoding="utf-8")
                    tpl = _convert_esphome_native(raw, f.name, raw_text)
                # Format 3: our internal template format
                elif raw.get("registers") or raw.get("connection_type"):
                    tpl = _normalize_template(raw, f.name)
                else:
                    _LOGGER.debug("Skipping %s — unrecognized format", f.name)
                    continue
            else:
                _LOGGER.debug("Skipping %s — unrecognized root type", f.name)
                continue
            if tpl:
                key = f"ext_{f.stem}"
                templates[key] = tpl
                _LOGGER.info(
                    "Loaded external template: %s -> key=%s name='%s'",
                    f.name, key, tpl["name"],
                )

        except Exception as e:
            _LOGGER.error("Failed to load template %s: %s", f.name, e)

    return templates


async def load_external_templates(hass) -> Dict[str, Dict[str, Any]]:
    """Async — runs blocking I/O in executor."""
    return await hass.async_add_executor_job(
        _load_templates_sync, hass.config.config_dir
    )


async def list_external_template_names(hass) -> Dict[str, str]:
    """Return {key: display_name} for UI dropdown."""
    templates = await load_external_templates(hass)
    result = {}
    for k, v in templates.items():
        conn = v.get("connection_type", "")
        pt = v.get("passthrough_type", "")
        if pt == "ha_modbus_sensors":
            tag = "Modbus sensors list"
        elif v.get("passthrough"):
            tag = "ESPHome passthrough"
        elif conn == "modbus_tcp":
            tag = "Modbus TCP"
        elif conn == "modbus_rtu":
            tag = "Modbus RTU"
        elif conn == "esphome":
            tag = "ESPHome"
        else:
            tag = conn
        result[k] = f"\U0001f4c4 {v['name']} ({tag})"
    return result


async def get_external_template(hass, key: str) -> Optional[Dict[str, Any]]:
    """Get a single external template by key."""
    templates = await load_external_templates(hass)
    return templates.get(key)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_register_address(value: Any) -> int:
    """Accept int, decimal string, or hex string like '0x000E'."""
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if s.lower().startswith("0x"):
        return int(s, 16)
    return int(s)


def _normalize_template(raw: Dict[str, Any], source_file: str) -> Optional[Dict[str, Any]]:
    """Validate and normalise a raw template dict."""
    if not isinstance(raw, dict):
        _LOGGER.warning("Template %s: root must be a dict", source_file)
        return None

    name = raw.get("name") or Path(source_file).stem
    conn_type = raw.get("connection_type", "esphome")
    registers_raw = raw.get("registers", [])

    registers = []
    for i, reg in enumerate(registers_raw):
        if not isinstance(reg, dict):
            continue
        if set(reg.keys()) <= {"_description"}:
            continue
        try:
            normalized = {k: v for k, v in reg.items() if not k.startswith("_")}
            if "register" in normalized:
                normalized["register"] = _parse_register_address(normalized["register"])
            registers.append(normalized)
        except Exception as e:
            _LOGGER.warning("Template %s register[%d] parse error: %s", source_file, i, e)

    result = {
        "name": name,
        "connection_type": conn_type,
        "scan_interval": raw.get("scan_interval", 5),
        "connection_params": raw.get("connection_params", {}),
        "registers": registers,
    }
    for k in ("globals", "extras"):
        if k in raw:
            result[k] = raw[k]
    return result


# ── Native ESPHome YAML converter ────────────────────────────────────────────

def _convert_esphome_native(data: dict, source_file: str, raw_text: str = "") -> Optional[Dict[str, Any]]:
    """
    Store native ESPHome YAML as a passthrough template.
    Only global params (name, pins, board, slave) are extracted for the UI form.
    The full original YAML text is stored and used 1:1 at generation time.
    """
    esp = data.get("esphome", {})
    uart = data.get("uart", {})
    mc_list = data.get("modbus_controller", [])
    mc = (mc_list[0] if isinstance(mc_list, list) else mc_list) or {}
    board_data = data.get("esp32") or data.get("esp8266") or {}
    platform = "ESP32" if "esp32" in data else "ESP8266"

    name = esp.get("friendly_name") or esp.get("name") or Path(source_file).stem

    return {
        "name": name,
        "connection_type": "esphome",
        "passthrough": True,              # signals generator to use raw YAML
        "passthrough_yaml": raw_text,     # original YAML text
        "scan_interval": _parse_interval(mc.get("update_interval", "5s")),
        "connection_params": {
            "platform": platform,
            "board": board_data.get("board", "esp32dev"),
            "tx_pin": uart.get("tx_pin", "GPIO15"),
            "rx_pin": uart.get("rx_pin", "GPIO14"),
            "baudrate": uart.get("baud_rate", 9600),
            "slave": mc.get("address", 1),
            "parity": "NONE",
            "stop_bits": uart.get("stop_bits", 1),
        },
        "registers": [],  # not used in passthrough mode
        # Store original values so substitution knows what to replace
        "_orig": {
            "name": esp.get("name", ""),
            "friendly_name": esp.get("friendly_name", ""),
            "board": board_data.get("board", ""),
            "tx_pin": uart.get("tx_pin", ""),
            "rx_pin": uart.get("rx_pin", ""),
            "baud_rate": str(uart.get("baud_rate", "")),
            "stop_bits": str(uart.get("stop_bits", "")),
            "update_interval": mc.get("update_interval", "5s"),
        },
    }


def _parse_interval(val: str) -> int:
    try:
        return int(str(val).rstrip("s"))
    except Exception:
        return 5


def _vtype_to_dtype(vtype: str) -> str:
    return {
        "U_WORD": "uint16", "S_WORD": "int16",
        "U_DWORD": "uint32", "S_DWORD": "int32",
        "FP32": "float32",
    }.get(str(vtype).upper(), "uint16")


def _copy_common(src: dict, dst: dict) -> None:
    """Copy shared fields from ESPHome entity to our register dict."""
    mapping = {
        "unit_of_measurement": "unit",
        "device_class": "device_class",
        "state_class": "state_class",
        "accuracy_decimals": "accuracy_decimals",
        "icon": "icon",
        "internal": "internal",
    }
    for src_k, dst_k in mapping.items():
        if src.get(src_k) is not None:
            dst[dst_k] = src[src_k]


def _filters_to_yaml(filters) -> str:
    """Convert ESPHome filters list back to YAML string."""
    if not isinstance(filters, list):
        return str(filters)
    import yaml as _y
    lines = []
    for f in filters:
        if isinstance(f, dict):
            for k, v in f.items():
                if isinstance(v, str) and "\n" in v:
                    lines.append(f"- {k}: |-")
                    for line in v.splitlines():
                        lines.append(f"    {line.strip()}")
                else:
                    lines.append(f"- {k}: {v}")
        else:
            lines.append(f"- {f}")
    return "\n".join(lines)


def _extract_bitmask_texts(on_value) -> tuple:
    """Try to extract text_sensor id and true/false texts from on_value lambda."""
    import re
    if not on_value:
        return None, "true", "false"
    then = on_value.get("then", [])
    lambda_code = ""
    if isinstance(then, list):
        for item in then:
            if isinstance(item, dict) and "lambda" in item:
                lambda_code = str(item["lambda"])
    elif isinstance(then, dict) and "lambda" in then:
        lambda_code = str(then["lambda"])

    # Extract: if (x) id(SENSOR_ID).publish_state("TRUE_TEXT"); else ... ("FALSE_TEXT")
    m = re.search(r'id\((\w+)\)\.publish_state\("([^"]+)"\).*publish_state\("([^"]+)"\)', lambda_code, re.DOTALL)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None, "true", "false"