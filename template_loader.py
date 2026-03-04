"""External template loader for Heat Pump Configurator.

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
            "# Heat Pump Configurator — External Templates\n\n"
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

            if not isinstance(raw, dict):
                _LOGGER.debug("Skipping %s — not a dict", f.name)
                continue

            # Native ESPHome YAML: has 'esphome:' key with sensor:/select: sections
            if raw.get("esphome") and (raw.get("sensor") or raw.get("select")):
                tpl = _convert_esphome_native(raw, f.name)
            elif raw.get("registers") or raw.get("connection_type"):
                tpl = _normalize_template(raw, f.name)
            else:
                _LOGGER.debug("Skipping %s — unrecognized format", f.name)
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
    return {k: f"\U0001f4c4 {v['name']} (externa)" for k, v in templates.items()}


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

def _convert_esphome_native(data: dict, source_file: str) -> Optional[Dict[str, Any]]:
    """
    Convert a native ESPHome YAML (with esphome:, sensor:, select: sections)
    into our internal template format.
    """
    esp = data.get("esphome", {})
    uart = data.get("uart", {})
    mc_list = data.get("modbus_controller", [])
    mc = (mc_list[0] if isinstance(mc_list, list) else mc_list) or {}

    name = esp.get("friendly_name") or esp.get("name") or Path(source_file).stem

    # Detect board platform
    platform = "ESP32" if "esp32" in data else "ESP8266"
    board = (data.get("esp32") or data.get("esp8266") or {}).get("board", "esp32dev")

    conn = {
        "platform": platform,
        "board": board,
        "tx_pin": uart.get("tx_pin", "GPIO15"),
        "rx_pin": uart.get("rx_pin", "GPIO14"),
        "baudrate": uart.get("baud_rate", 9600),
        "slave": mc.get("address", 1),
        "parity": "NONE",
        "stop_bits": uart.get("stop_bits", 1),
    }

    scan_raw = mc.get("update_interval", "5s")
    try:
        scan_interval = int(str(scan_raw).rstrip("s"))
    except Exception:
        scan_interval = 5

    registers = []

    # ── sensors ──────────────────────────────────────────────────────────────
    for s in data.get("sensor", []):
        platform_s = s.get("platform", "")

        if platform_s == "modbus_controller":
            reg = {
                "name": s.get("id") or s.get("name", "sensor"),
                "friendly_name": s.get("name", ""),
                "register": s.get("address", 0),
                "register_type": s.get("register_type", "holding"),
                "data_type": _vtype_to_dtype(s.get("value_type", "U_WORD")),
                "entity_type": "sensor",
            }
            _copy_common(s, reg)
            filters = s.get("filters")
            if filters:
                reg["custom_filters"] = _filters_to_yaml(filters)
            if s.get("bitmask"):
                reg["bitmask"] = hex(s["bitmask"]) if isinstance(s["bitmask"], int) else str(s["bitmask"])
                reg["entity_type"] = "bitmask_sensor"
                # Try to find linked text_sensor via on_value
                on_val = s.get("on_value", {})
                ts_id, true_t, false_t = _extract_bitmask_texts(on_val)
                if ts_id:
                    reg["text_sensor_id"] = ts_id
                    reg["true_text"] = true_t
                    reg["false_text"] = false_t
            registers.append(reg)

        elif platform_s == "integration":
            reg = {
                "name": s.get("id") or s.get("name", "integration"),
                "friendly_name": s.get("name", ""),
                "entity_type": "integration_sensor",
                "integration_source": s.get("sensor", ""),
                "integration_time_unit": s.get("time_unit", "h"),
                "restore": s.get("restore", True),
            }
            _copy_common(s, reg)
            registers.append(reg)

        elif platform_s == "template":
            reg = {
                "name": s.get("id") or s.get("name", "template_sensor"),
                "friendly_name": s.get("name", ""),
                "entity_type": "sensor",
                "register": 0,
                "register_type": "holding",
                "data_type": "uint16",
            }
            _copy_common(s, reg)
            if s.get("lambda"):
                reg["custom_filters"] = f'- lambda: |-\n    {s["lambda"]}'
            registers.append(reg)

    # ── binary sensors ───────────────────────────────────────────────────────
    for s in data.get("binary_sensor", []):
        if s.get("platform") == "modbus_controller":
            reg = {
                "name": s.get("id") or s.get("name", "binary"),
                "friendly_name": s.get("name", ""),
                "register": s.get("address", 0),
                "register_type": s.get("register_type", "holding"),
                "data_type": _vtype_to_dtype(s.get("value_type", "U_WORD")),
                "entity_type": "binary_sensor",
            }
            if s.get("bitmask"):
                reg["bitmask"] = hex(s["bitmask"]) if isinstance(s["bitmask"], int) else str(s["bitmask"])
            _copy_common(s, reg)
            registers.append(reg)

    # ── numbers ──────────────────────────────────────────────────────────────
    for s in data.get("number", []):
        if s.get("platform") == "modbus_controller":
            reg = {
                "name": s.get("id") or s.get("name", "number"),
                "friendly_name": s.get("name", ""),
                "register": s.get("address", 0),
                "register_type": s.get("register_type", "holding"),
                "data_type": _vtype_to_dtype(s.get("value_type", "U_WORD")),
                "entity_type": "number",
                "min": s.get("min_value", 0),
                "max": s.get("max_value", 100),
                "step": s.get("step", 1),
            }
            _copy_common(s, reg)
            registers.append(reg)

    # ── selects ──────────────────────────────────────────────────────────────
    for s in data.get("select", []):
        if s.get("platform") == "modbus_controller":
            reg = {
                "name": s.get("id") or s.get("name", "select"),
                "friendly_name": s.get("name", ""),
                "register": s.get("address", 0),
                "register_type": s.get("register_type", "holding"),
                "data_type": _vtype_to_dtype(s.get("value_type", "U_WORD")),
                "entity_type": "select",
            }
            om = s.get("optionsmap")
            if om:
                reg["options_map"] = json.dumps(om) if isinstance(om, dict) else str(om)
            if s.get("lambda"):
                reg["select_lambda"] = str(s["lambda"])
            if s.get("write_lambda"):
                reg["select_write_lambda"] = str(s["write_lambda"])
            _copy_common(s, reg)
            registers.append(reg)

    # ── text sensors ─────────────────────────────────────────────────────────
    for s in data.get("text_sensor", []):
        if s.get("platform") == "template":
            reg = {
                "name": s.get("id") or s.get("name", "text_sensor"),
                "friendly_name": s.get("name", ""),
                "entity_type": "text_sensor",
            }
            if s.get("lambda"):
                reg["lambda"] = str(s["lambda"])
            if s.get("update_interval"):
                reg["update_interval"] = s["update_interval"]
            _copy_common(s, reg)
            registers.append(reg)

    # ── switches ─────────────────────────────────────────────────────────────
    for s in data.get("switch", []):
        if s.get("platform") == "modbus_controller":
            reg = {
                "name": s.get("id") or s.get("name", "switch"),
                "friendly_name": s.get("name", ""),
                "register": s.get("address", 0),
                "register_type": s.get("register_type", "coil"),
                "data_type": "uint16",
                "entity_type": "switch",
            }
            registers.append(reg)

    modbus_cfg = data.get("modbus", {})
    extras = {
        "modbus_send_wait_time": modbus_cfg.get("send_wait_time", "200ms"),
        "esp_status_sensor": True,
        "esp_ip_sensor": True,
        "restart_switch": True,
    }

    return {
        "name": name,
        "connection_type": "esphome",
        "scan_interval": scan_interval,
        "connection_params": conn,
        "registers": registers,
        "extras": extras,
    }


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