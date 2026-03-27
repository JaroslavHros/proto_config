"""Config flow for ProtoConfig v0.2."""
import json
import logging
from typing import Any, Dict, List, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import (
    CONF_CONNECTION_TYPE, CONF_DEVICE_NAME, CONF_MODBUS_HOST,
    CONF_MODBUS_PORT, CONF_MODBUS_SLAVE, CONF_SCAN_INTERVAL,
    CONN_MODBUS_RTU, CONN_MODBUS_TCP, CONN_ESPHOME,
    CONNECTION_TYPES, DATA_TYPES, DEFAULT_MODBUS_PORT, DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE_ID, DEVICE_CLASSES_SENSOR, DOMAIN,
    ENTITY_TYPES_MODBUS, ENTITY_TYPES_ESPHOME, ESPHOME_ICONS,
    REGISTER_TYPES, STATE_CLASSES,
    ENTITY_SENSOR, ENTITY_BINARY_SENSOR, ENTITY_NUMBER, ENTITY_SELECT,
    ENTITY_TEXT_SENSOR, ENTITY_INTEGRATION_SENSOR, ENTITY_BITMASK_SENSOR,
    TEMPLATES,
)

_LOGGER = logging.getLogger(__name__)

USE_TEMPLATE = "__use_template__"
NO_TEMPLATE = "none"


def _parse_address(value: str, fmt: str) -> int:
    value = str(value).strip()
    if not value:
        raise ValueError("Empty address")
    if fmt == "hex":
        if not value.lower().startswith("0x"):
            value = "0x" + value
        addr = int(value, 16)
    else:
        addr = int(value)
    if not (0 <= addr <= 65535):
        raise ValueError(f"Address {addr} out of range")
    return addr


def _fmt_addr(addr: int) -> str:
    return f"{addr} (0x{addr:04X})"


def _normalize_and_validate_filters(raw: str):
    """
    Normalize and validate custom_filters input from UI.

    The UI text field returns a plain string. Users can write filters in two ways:

    Simple (single line per filter):
        - multiply: 0.1
        - offset: -50

    With lambda (multi-line, using \\n as line separator in the UI field):
        - multiply: 0.1
        - lambda: |-\\n    if (x < 0) return 0.0f;\\n    return x;

    Problems this function solves:
    1. HA UI field sends literal \\n escape sequences instead of real newlines.
    2. YAML block scalar  |-  syntax is not valid inside a flow/inline string —
       we must convert it to a proper quoted scalar before parsing.
    3. Users may accidentally omit the leading dash on the first item.

    Returns (normalized_str, error_key) where error_key is None on success.
    """
    import yaml as _y
    import re

    # Step 1: convert literal \\n sequences to real newlines
    text = raw.replace("\\n", "\n")

    # Step 2: try direct parse — works for simple filters without lambda block
    try:
        parsed = _y.safe_load(text)
        if isinstance(parsed, list):
            # Re-dump to normalised YAML string we store
            return _y.dump(parsed, allow_unicode=True, default_flow_style=False).strip(), None
        else:
            return None, "must_be_list"
    except _y.YAMLError:
        pass

    # Step 3: handle  |- block scalar inside a list item
    # Replace  "lambda: |-\n<indented lines>"  with a proper quoted scalar
    # Strategy: rebuild line by line, collecting block scalar bodies
    lines = text.splitlines()
    rebuilt = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect a mapping value that starts a block scalar:  key: |-  or  key: |
        block_match = re.match(r'^(\s*-?\s*)(\w+):\s*\|[-]?\s*$', line)
        if block_match:
            prefix = block_match.group(1)
            key = block_match.group(2)
            # Collect all following lines that are more indented than the key line
            base_indent = len(line) - len(line.lstrip())
            body_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if next_line.strip() == "":
                    i += 1
                    break
                next_indent = len(next_line) - len(next_line.lstrip())
                if next_indent > base_indent:
                    body_lines.append(next_line.strip())
                    i += 1
                else:
                    break
            # Encode as a double-quoted scalar with \n
            body_escaped = "\\n".join(body_lines).replace('"', '\\"')
            rebuilt.append(f'{prefix}{key}: "{body_escaped}"')
        else:
            rebuilt.append(line)
            i += 1

    rebuilt_text = "\n".join(rebuilt)

    try:
        parsed = _y.safe_load(rebuilt_text)
        if isinstance(parsed, list):
            # Store original (with real newlines) so generator can use it
            return text.strip(), None
        else:
            return None, "must_be_list"
    except _y.YAMLError as e:
        return None, "invalid_yaml"


# ─────────────────────────────────────────────────────────────────────────────
# Main Config Flow
# ─────────────────────────────────────────────────────────────────────────────


def _apply_passthrough_substitutions(device_config: dict, user_input: dict) -> None:
    """
    Apply user-specified substitutions to the passthrough YAML text.
    Replaces: esphome name, friendly_name, board, tx_pin, rx_pin, baud_rate,
              stop_bits, modbus_controller update_interval.
    """
    yaml_text = device_config.get("passthrough_yaml", "")
    if not yaml_text:
        return

    orig = device_config.get("_orig", {})
    conn = device_config.get("connection_params", {})

    def replace_yaml_value(text, key, old_val, new_val):
        """Replace a specific key: value in YAML text."""
        import re
        if not old_val or str(old_val) == str(new_val):
            return text
        old_s = str(old_val)
        new_s = str(new_val)
        # Match:  key: old_val  with optional surrounding quotes
        for quote in ['', '"', "'"]:
            old_pattern = f"{key}: {quote}{re.escape(old_s)}{quote}"
            new_pattern = f"{key}: {quote}{new_s}{quote}"
            if old_pattern in text:
                text = text.replace(old_pattern, new_pattern)
                return text
        return text

    new_name = user_input.get("esp_name", orig.get("name", ""))
    old_name = orig.get("name", "")
    old_friendly = orig.get("friendly_name", "")

    # Replace esphome.name
    if new_name and new_name != old_name:
        yaml_text = replace_yaml_value(yaml_text, "name", old_name, new_name)
    # Replace esphome.friendly_name (capitalize new name)
    if new_name and old_friendly:
        yaml_text = replace_yaml_value(yaml_text, "friendly_name", old_friendly, new_name.replace("_", " ").title())

    # Replace board
    new_board = user_input.get("board", "")
    if new_board and new_board != orig.get("board", ""):
        yaml_text = replace_yaml_value(yaml_text, "board", orig["board"], new_board)

    # Replace UART pins and settings
    for key, orig_key, ui_key in [
        ("tx_pin", "tx_pin", "tx_pin"),
        ("rx_pin", "rx_pin", "rx_pin"),
        ("baud_rate", "baud_rate", "baudrate"),
        ("stop_bits", "stop_bits", "stop_bits"),
    ]:
        old_v = orig.get(orig_key, "")
        new_v = user_input.get(ui_key, "")
        if old_v and new_v and str(old_v) != str(new_v):
            yaml_text = replace_yaml_value(yaml_text, key, old_v, new_v)

    # Replace modbus_controller update_interval
    old_interval = orig.get("update_interval", "5s")
    new_interval = f"{user_input.get('scan_interval', 5)}s" if user_input.get("scan_interval") else None
    if new_interval and new_interval != old_interval:
        yaml_text = replace_yaml_value(yaml_text, "update_interval", old_interval, new_interval)

    device_config["passthrough_yaml"] = yaml_text

class ProtoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Multi-step config flow."""

    VERSION = 1

    def __init__(self):
        self._device_config: Dict[str, Any] = {}
        self._registers: List[Dict] = []

    def _is_esphome(self):
        return self._device_config.get("connection_type") == CONN_ESPHOME

    def _is_modbus(self):
        return self._device_config.get("connection_type") in (CONN_MODBUS_TCP, CONN_MODBUS_RTU)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ProtoOptionsFlow(config_entry)

    # ── Step 1: device name + connection type ─────────────────────────────
    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            self._device_config["name"] = user_input[CONF_DEVICE_NAME]
            self._device_config["connection_type"] = user_input[CONF_CONNECTION_TYPE]
            self._device_config["scan_interval"] = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

            template_choice = user_input.get("template", NO_TEMPLATE)
            if template_choice and template_choice != NO_TEMPLATE:
                return await self.async_step_apply_template(template_choice)

            ct = user_input[CONF_CONNECTION_TYPE]
            if ct == CONN_MODBUS_TCP:
                return await self.async_step_modbus_tcp()
            elif ct == CONN_MODBUS_RTU:
                return await self.async_step_modbus_rtu()
            elif ct == CONN_ESPHOME:
                return await self.async_step_esphome()

        # Build template dropdown — built-in + external from heatpump_templates/
        from .template_loader import list_external_template_names, ensure_templates_dir
        await ensure_templates_dir(self.hass)
        template_options = {NO_TEMPLATE: "— Bez šablóny —"}
        template_options.update(TEMPLATES)
        template_options.update(await list_external_template_names(self.hass))

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_DEVICE_NAME): str,
                vol.Required(CONF_CONNECTION_TYPE, default=CONN_MODBUS_TCP): vol.In(CONNECTION_TYPES),
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.positive_int,
                vol.Optional("template", default=NO_TEMPLATE): vol.In(template_options),
            }),
            errors=errors,
        )

    # ── Step: apply template ──────────────────────────────────────────────
    async def async_step_apply_template(self, template_name: str) -> FlowResult:
        from .templates import get_template
        from .template_loader import get_external_template

        # External template (key starts with ext_)
        if template_name.startswith("ext_"):
            tpl = await get_external_template(self.hass, template_name)
        else:
            tpl = get_template(template_name)

        if not tpl:
            return await self.async_step_user()

        # Override with user-chosen name / connection_type / scan_interval
        tpl["name"] = self._device_config.get("name", tpl.get("name", "heat_pump"))
        if self._device_config.get("connection_type"):
            tpl["connection_type"] = self._device_config["connection_type"]
        if self._device_config.get("scan_interval"):
            tpl["scan_interval"] = self._device_config["scan_interval"]

        self._device_config = tpl
        self._registers = list(tpl.get("registers", []))

        conn_type = tpl.get("connection_type", CONN_ESPHOME)
        if conn_type == CONN_ESPHOME:
            return await self.async_step_esphome_template()
        elif conn_type == CONN_MODBUS_TCP:
            return await self.async_step_modbus_tcp()
        else:
            return await self.async_step_modbus_rtu()

    async def async_step_esphome_template(self, user_input=None) -> FlowResult:
        """Let user confirm/adjust ESP connection params from the template."""
        tpl_conn = self._device_config.get("connection_params", {})
        is_passthrough = self._device_config.get("passthrough", False)

        if user_input is not None:
            self._device_config["connection_params"] = {
                "platform": user_input.get("platform", "ESP32"),
                "board": user_input.get("board", "esp32dev"),
                "tx_pin": user_input["tx_pin"],
                "rx_pin": user_input["rx_pin"],
                "baudrate": user_input["baudrate"],
                "slave": user_input[CONF_MODBUS_SLAVE],
                "parity": user_input.get("parity", "NONE"),
                "stop_bits": user_input.get("stop_bits", 1),
            }
            if is_passthrough:
                new_name = user_input.get("esp_name", "").strip()
                if new_name:
                    self._device_config["name"] = new_name
                _apply_passthrough_substitutions(self._device_config, user_input)
            return await self.async_step_finish()

        schema_dict = {}
        if is_passthrough:
            schema_dict[vol.Required("esp_name", default=self._device_config.get("name", ""))] = str
        schema_dict.update({
            vol.Required("platform", default=tpl_conn.get("platform", "ESP32")): vol.In(["ESP32", "ESP8266"]),
            vol.Required("board", default=tpl_conn.get("board", "esp32dev")): str,
            vol.Required("tx_pin", default=tpl_conn.get("tx_pin", "GPIO15")): str,
            vol.Required("rx_pin", default=tpl_conn.get("rx_pin", "GPIO14")): str,
            vol.Required("baudrate", default=tpl_conn.get("baudrate", 9600)): vol.In([9600, 19200, 38400, 115200]),
            vol.Required(CONF_MODBUS_SLAVE, default=tpl_conn.get("slave", 1)): cv.positive_int,
            vol.Optional("parity", default=tpl_conn.get("parity", "NONE")): vol.In(["NONE", "EVEN", "ODD"]),
            vol.Optional("stop_bits", default=tpl_conn.get("stop_bits", 1)): vol.In([1, 2]),
        })
        mode_info = "Passthrough rezim: YAML sa pouzije 1:1, upravia sa len globalne parametre." if is_passthrough else f"Template nacitany s {len(self._registers)} registrami."
        return self.async_show_form(
            step_id="esphome_template",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "register_count": str(len(self._registers)),
                "template_info": mode_info,
            },
        )

    # ── Step: Modbus TCP ──────────────────────────────────────────────────
    async def async_step_modbus_tcp(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._device_config["connection_params"] = {
                "host": user_input[CONF_MODBUS_HOST],
                "port": user_input[CONF_MODBUS_PORT],
                "slave": user_input[CONF_MODBUS_SLAVE],
            }
            # Passthrough templates already have registers — skip wizard
            if self._device_config.get("passthrough"):
                return await self.async_step_finish()
            return await self.async_step_add_register()

        return self.async_show_form(
            step_id="modbus_tcp",
            data_schema=vol.Schema({
                vol.Required(CONF_MODBUS_HOST): str,
                vol.Required(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): cv.port,
                vol.Required(CONF_MODBUS_SLAVE, default=DEFAULT_SLAVE_ID): cv.positive_int,
            }),
        )

    # ── Step: Modbus RTU ──────────────────────────────────────────────────
    async def async_step_modbus_rtu(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._device_config["connection_params"] = {
                "port": user_input["serial_port"],
                "baudrate": user_input["baudrate"],
                "slave": user_input[CONF_MODBUS_SLAVE],
                "parity": user_input.get("parity", "N"),
                "stop_bits": user_input.get("stop_bits", 1),
            }
            # Passthrough templates already have registers — skip wizard
            if self._device_config.get("passthrough"):
                return await self.async_step_finish()
            return await self.async_step_add_register()

        return self.async_show_form(
            step_id="modbus_rtu",
            data_schema=vol.Schema({
                vol.Required("serial_port", default="/dev/ttyUSB0"): str,
                vol.Required("baudrate", default=9600): vol.In([9600, 19200, 38400, 115200]),
                vol.Required(CONF_MODBUS_SLAVE, default=DEFAULT_SLAVE_ID): cv.positive_int,
                vol.Optional("parity", default="N"): vol.In(["N", "E", "O"]),
                vol.Optional("stop_bits", default=1): vol.In([1, 2]),
            }),
        )

    # ── Step: ESPHome ─────────────────────────────────────────────────────
    async def async_step_esphome(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._device_config["connection_params"] = {
                "platform": user_input.get("platform", "ESP32"),
                "board": user_input.get("board", "esp32dev"),
                "tx_pin": user_input["tx_pin"],
                "rx_pin": user_input["rx_pin"],
                "baudrate": user_input["baudrate"],
                "slave": user_input[CONF_MODBUS_SLAVE],
                "parity": user_input.get("parity", "NONE"),
                "stop_bits": user_input.get("stop_bits", 1),
            }
            return await self.async_step_add_register()

        return self.async_show_form(
            step_id="esphome",
            data_schema=vol.Schema({
                vol.Required("platform", default="ESP32"): vol.In(["ESP32", "ESP8266"]),
                vol.Required("board", default="esp32dev"): str,
                vol.Required("tx_pin", default="GPIO17"): str,
                vol.Required("rx_pin", default="GPIO16"): str,
                vol.Required("baudrate", default=9600): vol.In([9600, 19200, 38400, 115200]),
                vol.Required(CONF_MODBUS_SLAVE, default=DEFAULT_SLAVE_ID): cv.positive_int,
                vol.Optional("parity", default="NONE"): vol.In(["NONE", "EVEN", "ODD"]),
                vol.Optional("stop_bits", default=1): vol.In([1, 2]),
            }),
        )

    # ── Step: add register ────────────────────────────────────────────────
    async def async_step_add_register(self, user_input=None) -> FlowResult:
        errors = {}

        if user_input is not None:
            entity_type = user_input.get("entity_type", ENTITY_SENSOR)

            # Special entity types (ESPHome only)
            if entity_type == ENTITY_INTEGRATION_SENSOR:
                return await self.async_step_add_integration_sensor()
            if entity_type == ENTITY_TEXT_SENSOR:
                return await self.async_step_add_text_sensor()
            if entity_type == ENTITY_BITMASK_SENSOR:
                return await self.async_step_add_bitmask_sensor()

            if user_input.get("done", False):
                if not self._registers:
                    errors["base"] = "no_registers"
                else:
                    return await self.async_step_finish()
            else:
                try:
                    addr_fmt = user_input.get("address_format", "decimal")
                    address = _parse_address(user_input["register_address"], addr_fmt)
                    reg = {
                        "name": user_input["register_name"],
                        "friendly_name": user_input["friendly_name"],
                        "register": address,
                        "register_type": user_input["register_type"],
                        "data_type": user_input["data_type"],
                        "entity_type": entity_type,
                    }
                    for k in ["scale", "offset", "unit", "device_class", "state_class"]:
                        if user_input.get(k):
                            reg[k] = user_input[k]
                    if self._is_esphome():
                        for k in ["accuracy_decimals", "icon", "custom_filters"]:
                            if user_input.get(k):
                                reg[k] = user_input[k]
                        if reg.get("custom_filters"):
                            normalized, err = _normalize_and_validate_filters(reg["custom_filters"])
                            if err:
                                errors["custom_filters"] = err
                            else:
                                reg["custom_filters"] = normalized
                        if entity_type == "binary_sensor" and user_input.get("bitmask"):
                            reg["bitmask"] = user_input["bitmask"]
                        if entity_type == ENTITY_SELECT:
                            if user_input.get("options_map"):
                                reg["options_map"] = user_input["options_map"]
                            if user_input.get("select_lambda"):
                                reg["select_lambda"] = user_input["select_lambda"]
                            if user_input.get("select_write_lambda"):
                                reg["select_write_lambda"] = user_input["select_write_lambda"]
                    else:
                        for k in ["precision", "scan_interval"]:
                            if user_input.get(k) is not None:
                                reg[k] = user_input[k]
                        if entity_type == ENTITY_SELECT and user_input.get("options_map"):
                            reg["options_map"] = user_input["options_map"]
                    if entity_type == ENTITY_NUMBER:
                        for k in ["min", "max", "step"]:
                            if user_input.get(k) is not None:
                                reg[k] = user_input[k]
                    if self._is_esphome():
                        reg["internal"] = bool(user_input.get("internal", False))
                    if not errors:
                        self._registers.append(reg)
                        _LOGGER.info("Added register '%s' @ %s", reg["name"], _fmt_addr(address))
                except ValueError as e:
                    errors["register_address"] = "invalid_address"

        has_regs = len(self._registers) > 0
        device_type = "ESPHome" if self._is_esphome() else "Modbus"
        entity_types = ENTITY_TYPES_ESPHOME if self._is_esphome() else ENTITY_TYPES_MODBUS

        schema_dict = {
            vol.Required("register_name", default=""): str,
            vol.Required("friendly_name", default=""): str,
            vol.Required("address_format", default="hex"): vol.In({
                "decimal": "Decimal (napr. 100, 8192)",
                "hex": "Hexadecimal (napr. 0x0001, 2000)",
            }),
            vol.Required("register_address"): str,
            vol.Required("register_type", default="holding"): vol.In(REGISTER_TYPES),
            vol.Required("data_type", default="uint16"): vol.In(DATA_TYPES),
            vol.Required("entity_type", default=ENTITY_SENSOR): vol.In(entity_types),
            vol.Optional("scale"): vol.Coerce(float),
            vol.Optional("offset"): vol.Coerce(float),
            vol.Optional("unit"): str,
            vol.Optional("device_class"): vol.In(DEVICE_CLASSES_SENSOR),
            vol.Optional("state_class"): vol.In(STATE_CLASSES),
        }

        if self._is_esphome():
            schema_dict.update({
                vol.Optional("accuracy_decimals"): cv.positive_int,
                vol.Optional("icon"): vol.In(ESPHOME_ICONS),
                vol.Optional("bitmask"): str,
                vol.Optional("options_map"): str,
                vol.Optional("select_lambda"): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional("select_write_lambda"): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional("custom_filters"): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional("internal", default=False): bool,
            })
        else:
            schema_dict.update({
                vol.Optional("precision"): cv.positive_int,
                vol.Optional("scan_interval"): cv.positive_int,
                vol.Optional("options_map"): str,
            })

        schema_dict.update({
            vol.Optional("min"): vol.Coerce(float),
            vol.Optional("max"): vol.Coerce(float),
            vol.Optional("step"): vol.Coerce(float),
        })

        if has_regs:
            schema_dict[vol.Optional("done", default=False)] = bool

        return self.async_show_form(
            step_id="add_register",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "register_count": str(len(self._registers)),
                "device_type": device_type,
            },
        )

    # ── Step: integration sensor ──────────────────────────────────────────
    async def async_step_add_integration_sensor(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            if not errors:
                reg = {
                    "name": user_input["register_name"],
                    "friendly_name": user_input["friendly_name"],
                    "entity_type": ENTITY_INTEGRATION_SENSOR,
                    "integration_source": user_input["integration_source"],
                    "integration_time_unit": user_input.get("integration_time_unit", "h"),
                    "restore": user_input.get("restore", True),
                }
                for k in ["unit", "device_class", "state_class", "accuracy_decimals"]:
                    if user_input.get(k):
                        reg[k] = user_input[k]
                self._registers.append(reg)
                return await self.async_step_add_register()

        return self.async_show_form(
            step_id="add_integration_sensor",
            data_schema=vol.Schema({
                vol.Required("register_name"): str,
                vol.Required("friendly_name"): str,
                vol.Required("integration_source"): str,
                vol.Required("integration_time_unit", default="h"): vol.In(["s", "min", "h", "d"]),
                vol.Optional("unit"): str,
                vol.Optional("device_class"): vol.In(DEVICE_CLASSES_SENSOR),
                vol.Optional("state_class", default="total_increasing"): vol.In(STATE_CLASSES),
                vol.Optional("accuracy_decimals"): cv.positive_int,
                vol.Optional("restore", default=True): bool,
            }),
            errors=errors,
        )

    # ── Step: text sensor ─────────────────────────────────────────────────
    async def async_step_add_text_sensor(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            reg = {
                "name": user_input["register_name"],
                "friendly_name": user_input["friendly_name"],
                "entity_type": ENTITY_TEXT_SENSOR,
                "text_sensor_template": True,
            }
            for k in ["update_interval", "lambda", "icon"]:
                if user_input.get(k):
                    reg[k] = user_input[k]
            self._registers.append(reg)
            return await self.async_step_add_register()

        return self.async_show_form(
            step_id="add_text_sensor",
            data_schema=vol.Schema({
                vol.Required("register_name"): str,
                vol.Required("friendly_name"): str,
                vol.Optional("update_interval", default="10s"): str,
                vol.Optional("lambda"): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional("icon"): vol.In(ESPHOME_ICONS),
            }),
            errors=errors,
        )

    # ── Step: bitmask sensor ──────────────────────────────────────────────
    async def async_step_add_bitmask_sensor(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            try:
                addr_fmt = user_input.get("address_format", "hex")
                address = _parse_address(user_input["register_address"], addr_fmt)
                reg = {
                    "name": user_input["register_name"],
                    "friendly_name": user_input["friendly_name"],
                    "register": address,
                    "register_type": user_input["register_type"],
                    "data_type": user_input.get("data_type", "uint16"),
                    "entity_type": ENTITY_BITMASK_SENSOR,
                    "bitmask": user_input["bitmask"],
                    "internal": user_input.get("internal", True),
                    "text_sensor_id": user_input["text_sensor_id"],
                    "text_sensor_name": user_input["text_sensor_name"],
                    "true_text": user_input.get("true_text", "Áno"),
                    "false_text": user_input.get("false_text", "Nie"),
                }
                if user_input.get("icon"):
                    reg["icon"] = user_input["icon"]
                if not errors:
                    self._registers.append(reg)
                    return await self.async_step_add_register()
            except ValueError:
                errors["register_address"] = "invalid_address"

        return self.async_show_form(
            step_id="add_bitmask_sensor",
            data_schema=vol.Schema({
                vol.Required("register_name"): str,
                vol.Required("friendly_name"): str,
                vol.Required("address_format", default="hex"): vol.In({"decimal": "Decimal", "hex": "Hexadecimal"}),
                vol.Required("register_address"): str,
                vol.Required("register_type", default="holding"): vol.In(REGISTER_TYPES),
                vol.Required("data_type", default="uint16"): vol.In(DATA_TYPES),
                vol.Required("bitmask"): str,
                vol.Required("text_sensor_id"): str,
                vol.Required("text_sensor_name"): str,
                vol.Optional("true_text", default="Áno"): str,
                vol.Optional("false_text", default="Nie"): str,
                vol.Optional("internal", default=True): bool,
                vol.Optional("icon"): vol.In(ESPHOME_ICONS),
            }),
            errors=errors,
        )

    # ── Step: finish ──────────────────────────────────────────────────────
    async def async_step_finish(self, user_input=None) -> FlowResult:
        self._device_config["registers"] = self._registers
        self._device_config["needs_generate"] = True
        return self.async_create_entry(
            title=self._device_config["name"],
            data=self._device_config,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Options Flow  (edit existing device)
# ─────────────────────────────────────────────────────────────────────────────

class ProtoOptionsFlow(config_entries.OptionsFlow):
    """Allow editing an existing device entry."""

    def __init__(self, config_entry):
        self._entry = config_entry
        # Merge options into data — same as async_setup_entry does
        # This ensures edits saved via _save() (which go to entry.options) are visible
        merged = {**config_entry.data, **config_entry.options}
        self._registers: List[Dict] = list(merged.get("registers", []))
        self._device_config: Dict = merged
        self._pending_delete: Optional[int] = None

    def _is_esphome(self):
        return self._device_config.get("connection_type") == CONN_ESPHOME

    # ── Options menu ──────────────────────────────────────────────────────
    async def async_step_init(self, user_input=None) -> FlowResult:
        reg_summary = "\n".join(
            f"  [{i}] {r.get('friendly_name', r.get('name', '?'))} @ {_fmt_addr(r['register']) if 'register' in r else '—'}"
            for i, r in enumerate(self._registers)
        ) or "  (no registers)"

        if user_input is not None:
            action = user_input.get("action")
            if action == "add_register":
                return await self.async_step_add_register()
            elif action == "add_integration":
                return await self.async_step_add_integration_sensor()
            elif action == "add_bitmask":
                return await self.async_step_add_bitmask_sensor()
            elif action == "add_text_sensor":
                return await self.async_step_add_text_sensor()
            elif action == "edit_connection":
                ct = self._device_config.get("connection_type")
                if ct == CONN_MODBUS_TCP:
                    return await self.async_step_edit_modbus_tcp()
                elif ct == CONN_MODBUS_RTU:
                    return await self.async_step_edit_modbus_rtu()
                elif ct == CONN_ESPHOME:
                    return await self.async_step_edit_esphome()
            elif action == "rename":
                return await self.async_step_rename()
            elif action == "delete_register":
                return await self.async_step_delete_register()
            elif action == "regenerate":
                return await self._do_regenerate()
            elif action == "save":
                return await self._save()

        action_choices = {
            "add_register": "➕ Add register",
            "edit_connection": "🔧 Edit connection parameters",
            "rename": "✏️ Rename device",
            "delete_register": "🗑️ Delete a register",
            "regenerate": "🔄 Regenerate & reload YAML",
            "save": "💾 Save changes",
        }
        if self._is_esphome():
            action_choices["add_integration"] = "📊 Add integration sensor"
            action_choices["add_bitmask"] = "🔢 Add bitmask sensor"
            action_choices["add_text_sensor"] = "📝 Add text sensor"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("action", default="add_register"): vol.In(action_choices),
            }),
            description_placeholders={"registers": reg_summary},
        )

    # ── Rename device ─────────────────────────────────────────────────────
    async def async_step_rename(self, user_input=None) -> FlowResult:
        if user_input is not None:
            new_name = user_input["name"].strip()
            if new_name:
                self._device_config["name"] = new_name
            return await self.async_step_init()

        return self.async_show_form(
            step_id="rename",
            data_schema=vol.Schema({
                vol.Required("name", default=self._device_config.get("name", "")): str,
            }),
        )

        # ── Edit connection params ────────────────────────────────────────────
    async def async_step_edit_modbus_tcp(self, user_input=None) -> FlowResult:
        cp = self._device_config.get("connection_params", {})
        if user_input is not None:
            self._device_config["connection_params"] = {
                "host": user_input[CONF_MODBUS_HOST],
                "port": user_input[CONF_MODBUS_PORT],
                "slave": user_input[CONF_MODBUS_SLAVE],
            }
            return await self.async_step_init()

        return self.async_show_form(
            step_id="edit_modbus_tcp",
            data_schema=vol.Schema({
                vol.Required(CONF_MODBUS_HOST, default=cp.get("host", "")): str,
                vol.Required(CONF_MODBUS_PORT, default=cp.get("port", DEFAULT_MODBUS_PORT)): cv.port,
                vol.Required(CONF_MODBUS_SLAVE, default=cp.get("slave", DEFAULT_SLAVE_ID)): cv.positive_int,
            }),
        )

    async def async_step_edit_modbus_rtu(self, user_input=None) -> FlowResult:
        cp = self._device_config.get("connection_params", {})
        if user_input is not None:
            self._device_config["connection_params"] = {
                "port": user_input["serial_port"],
                "baudrate": user_input["baudrate"],
                "slave": user_input[CONF_MODBUS_SLAVE],
                "parity": user_input.get("parity", "N"),
                "stop_bits": user_input.get("stop_bits", 1),
            }
            return await self.async_step_init()

        return self.async_show_form(
            step_id="edit_modbus_rtu",
            data_schema=vol.Schema({
                vol.Required("serial_port", default=cp.get("port", "/dev/ttyUSB0")): str,
                vol.Required("baudrate", default=cp.get("baudrate", 9600)): vol.In([9600, 19200, 38400, 115200]),
                vol.Required(CONF_MODBUS_SLAVE, default=cp.get("slave", DEFAULT_SLAVE_ID)): cv.positive_int,
                vol.Optional("parity", default=cp.get("parity", "N")): vol.In(["N", "E", "O"]),
                vol.Optional("stop_bits", default=cp.get("stop_bits", 1)): vol.In([1, 2]),
            }),
        )

    async def async_step_edit_esphome(self, user_input=None) -> FlowResult:
        cp = self._device_config.get("connection_params", {})
        if user_input is not None:
            self._device_config["connection_params"] = {
                "platform": user_input.get("platform", "ESP32"),
                "board": user_input.get("board", "esp32dev"),
                "tx_pin": user_input["tx_pin"],
                "rx_pin": user_input["rx_pin"],
                "baudrate": user_input["baudrate"],
                "slave": user_input[CONF_MODBUS_SLAVE],
                "parity": user_input.get("parity", "NONE"),
                "stop_bits": user_input.get("stop_bits", 1),
            }
            return await self.async_step_init()

        return self.async_show_form(
            step_id="edit_esphome",
            data_schema=vol.Schema({
                vol.Required("platform", default=cp.get("platform", "ESP32")): vol.In(["ESP32", "ESP8266"]),
                vol.Required("board", default=cp.get("board", "esp32dev")): str,
                vol.Required("tx_pin", default=cp.get("tx_pin", "GPIO17")): str,
                vol.Required("rx_pin", default=cp.get("rx_pin", "GPIO16")): str,
                vol.Required("baudrate", default=cp.get("baudrate", 9600)): vol.In([9600, 19200, 38400, 115200]),
                vol.Required(CONF_MODBUS_SLAVE, default=cp.get("slave", DEFAULT_SLAVE_ID)): cv.positive_int,
                vol.Optional("parity", default=cp.get("parity", "NONE")): vol.In(["NONE", "EVEN", "ODD"]),
                vol.Optional("stop_bits", default=cp.get("stop_bits", 1)): vol.In([1, 2]),
            }),
        )

    # ── Delete register ───────────────────────────────────────────────────
    async def async_step_delete_register(self, user_input=None) -> FlowResult:
        if not self._registers:
            return await self.async_step_init()

        if user_input is not None:
            idx = user_input.get("register_index")
            if idx is not None and 0 <= idx < len(self._registers):
                removed = self._registers.pop(idx)
                _LOGGER.info("Deleted register: %s", removed.get("name"))
            return await self.async_step_init()

        choices = {
            str(i): f"[{i}] {r.get('friendly_name', r.get('name', '?'))} @ {_fmt_addr(r['register']) if 'register' in r else '—'}"
            for i, r in enumerate(self._registers)
        }

        return self.async_show_form(
            step_id="delete_register",
            data_schema=vol.Schema({
                vol.Required("register_index"): vol.In({int(k): v for k, v in choices.items()}),
            }),
        )

    # ── Add register (same as config flow) ───────────────────────────────
    async def async_step_add_register(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            entity_type = user_input.get("entity_type", ENTITY_SENSOR)
            if entity_type == ENTITY_INTEGRATION_SENSOR:
                return await self.async_step_add_integration_sensor()
            if entity_type == ENTITY_TEXT_SENSOR:
                return await self.async_step_add_text_sensor()
            if entity_type == ENTITY_BITMASK_SENSOR:
                return await self.async_step_add_bitmask_sensor()

            try:
                addr_fmt = user_input.get("address_format", "hex")
                address = _parse_address(user_input["register_address"], addr_fmt)
                reg = {
                    "name": user_input["register_name"],
                    "friendly_name": user_input["friendly_name"],
                    "register": address,
                    "register_type": user_input["register_type"],
                    "data_type": user_input["data_type"],
                    "entity_type": entity_type,
                }
                for k in ["scale", "offset", "unit", "device_class", "state_class"]:
                    if user_input.get(k):
                        reg[k] = user_input[k]
                if self._is_esphome():
                    for k in ["accuracy_decimals", "icon", "bitmask", "options_map", "select_lambda", "select_write_lambda"]:
                        if user_input.get(k):
                            reg[k] = user_input[k]
                    reg["internal"] = bool(user_input.get("internal", False))
                    if user_input.get("custom_filters"):
                        normalized, err = _normalize_and_validate_filters(user_input["custom_filters"])
                        if err:
                            errors["custom_filters"] = err
                        else:
                            reg["custom_filters"] = normalized
                else:
                    for k in ["precision", "scan_interval", "options_map"]:
                        if user_input.get(k):
                            reg[k] = user_input[k]
                if entity_type == ENTITY_NUMBER:
                    for k in ["min", "max", "step"]:
                        if user_input.get(k) is not None:
                            reg[k] = user_input[k]
                if not errors:
                    self._registers.append(reg)
                    return await self.async_step_init()
            except ValueError:
                errors["register_address"] = "invalid_address"

        entity_types = ENTITY_TYPES_ESPHOME if self._is_esphome() else ENTITY_TYPES_MODBUS
        schema_dict = {
            vol.Required("register_name", default=""): str,
            vol.Required("friendly_name", default=""): str,
            vol.Required("address_format", default="hex"): vol.In({"decimal": "Decimal", "hex": "Hexadecimal"}),
            vol.Required("register_address"): str,
            vol.Required("register_type", default="holding"): vol.In(REGISTER_TYPES),
            vol.Required("data_type", default="uint16"): vol.In(DATA_TYPES),
            vol.Required("entity_type", default=ENTITY_SENSOR): vol.In(entity_types),
            vol.Optional("scale"): vol.Coerce(float),
            vol.Optional("offset"): vol.Coerce(float),
            vol.Optional("unit"): str,
            vol.Optional("device_class"): vol.In(DEVICE_CLASSES_SENSOR),
            vol.Optional("state_class"): vol.In(STATE_CLASSES),
        }
        if self._is_esphome():
            schema_dict.update({
                vol.Optional("accuracy_decimals"): cv.positive_int,
                vol.Optional("icon"): vol.In(ESPHOME_ICONS),
                vol.Optional("bitmask"): str,
                vol.Optional("options_map"): str,
                vol.Optional("select_lambda"): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional("select_write_lambda"): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional("custom_filters"): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional("internal", default=False): bool,
            })
        else:
            schema_dict.update({
                vol.Optional("precision"): cv.positive_int,
                vol.Optional("scan_interval"): cv.positive_int,
                vol.Optional("options_map"): str,
            })
        schema_dict.update({
            vol.Optional("min"): vol.Coerce(float),
            vol.Optional("max"): vol.Coerce(float),
            vol.Optional("step"): vol.Coerce(float),
        })

        return self.async_show_form(
            step_id="add_register",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={"register_count": str(len(self._registers)), "device_type": "ESPHome" if self._is_esphome() else "Modbus"},
        )

    # ── Add integration sensor ────────────────────────────────────────────
    async def async_step_add_integration_sensor(self, user_input=None) -> FlowResult:
        if user_input is not None:
            reg = {
                "name": user_input["register_name"],
                "friendly_name": user_input["friendly_name"],
                "entity_type": ENTITY_INTEGRATION_SENSOR,
                "integration_source": user_input["integration_source"],
                "integration_time_unit": user_input.get("integration_time_unit", "h"),
                "restore": user_input.get("restore", True),
            }
            for k in ["unit", "device_class", "state_class", "accuracy_decimals"]:
                if user_input.get(k):
                    reg[k] = user_input[k]
            self._registers.append(reg)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="add_integration_sensor",
            data_schema=vol.Schema({
                vol.Required("register_name"): str,
                vol.Required("friendly_name"): str,
                vol.Required("integration_source"): str,
                vol.Required("integration_time_unit", default="h"): vol.In(["s", "min", "h", "d"]),
                vol.Optional("unit"): str,
                vol.Optional("device_class"): vol.In(DEVICE_CLASSES_SENSOR),
                vol.Optional("state_class", default="total_increasing"): vol.In(STATE_CLASSES),
                vol.Optional("accuracy_decimals"): cv.positive_int,
                vol.Optional("restore", default=True): bool,
            }),
            errors={},
        )

    # ── Add text sensor ───────────────────────────────────────────────────
    async def async_step_add_text_sensor(self, user_input=None) -> FlowResult:
        if user_input is not None:
            reg = {
                "name": user_input["register_name"],
                "friendly_name": user_input["friendly_name"],
                "entity_type": ENTITY_TEXT_SENSOR,
                "text_sensor_template": True,
            }
            for k in ["update_interval", "lambda", "icon"]:
                if user_input.get(k):
                    reg[k] = user_input[k]
            self._registers.append(reg)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="add_text_sensor",
            data_schema=vol.Schema({
                vol.Required("register_name"): str,
                vol.Required("friendly_name"): str,
                vol.Optional("update_interval", default="10s"): str,
                vol.Optional("lambda"): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional("icon"): vol.In(ESPHOME_ICONS),
            }),
            errors={},
        )

    # ── Add bitmask sensor ────────────────────────────────────────────────
    async def async_step_add_bitmask_sensor(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            try:
                address = _parse_address(user_input["register_address"], user_input.get("address_format", "hex"))
                reg = {
                    "name": user_input["register_name"],
                    "friendly_name": user_input["friendly_name"],
                    "register": address,
                    "register_type": user_input["register_type"],
                    "data_type": user_input.get("data_type", "uint16"),
                    "entity_type": ENTITY_BITMASK_SENSOR,
                    "bitmask": user_input["bitmask"],
                    "internal": user_input.get("internal", True),
                    "text_sensor_id": user_input["text_sensor_id"],
                    "text_sensor_name": user_input["text_sensor_name"],
                    "true_text": user_input.get("true_text", "Áno"),
                    "false_text": user_input.get("false_text", "Nie"),
                }
                if user_input.get("icon"):
                    reg["icon"] = user_input["icon"]
                self._registers.append(reg)
                return await self.async_step_init()
            except ValueError:
                errors["register_address"] = "invalid_address"

        return self.async_show_form(
            step_id="add_bitmask_sensor",
            data_schema=vol.Schema({
                vol.Required("register_name"): str,
                vol.Required("friendly_name"): str,
                vol.Required("address_format", default="hex"): vol.In({"decimal": "Decimal", "hex": "Hexadecimal"}),
                vol.Required("register_address"): str,
                vol.Required("register_type", default="holding"): vol.In(REGISTER_TYPES),
                vol.Required("data_type", default="uint16"): vol.In(DATA_TYPES),
                vol.Required("bitmask"): str,
                vol.Required("text_sensor_id"): str,
                vol.Required("text_sensor_name"): str,
                vol.Optional("true_text", default="Áno"): str,
                vol.Optional("false_text", default="Nie"): str,
                vol.Optional("internal", default=True): bool,
                vol.Optional("icon"): vol.In(ESPHOME_ICONS),
            }),
            errors=errors,
        )

    # ── Helpers ───────────────────────────────────────────────────────────
    async def _do_regenerate(self) -> FlowResult:
        """Save and regenerate YAML for THIS device only."""
        result = await self._save()
        # Call reload service with specific device_id (entry_id) — not all devices
        await self.hass.services.async_call(
            DOMAIN, "reload",
            {"device_id": self.config_entry.entry_id},
        )
        return result

    async def _save(self) -> FlowResult:
        self._device_config["registers"] = self._registers
        # async_create_entry in OptionsFlow saves to entry.options
        # needs_generate must also land in entry.data so async_setup_entry sees it
        new_data = {**self.config_entry.data, **self._device_config, "needs_generate": True}
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        return self.async_create_entry(title=self._device_config["name"], data=self._device_config)