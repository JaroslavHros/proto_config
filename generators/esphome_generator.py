"""ESPHome YAML configuration generator — v0.2.
Supports: sensor, binary_sensor, number, switch, select,
          text_sensor, integration_sensor, bitmask_sensor,
          globals, modbus send_wait_time, ESP status/IP/restart extras.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..const import (
    DATA_TYPE_FLOAT32, DATA_TYPE_INT16, DATA_TYPE_INT32, DATA_TYPE_INT64,
    DATA_TYPE_UINT16, DATA_TYPE_UINT32, DATA_TYPE_UINT64,
    ENTITY_BINARY_SENSOR, ENTITY_NUMBER, ENTITY_SELECT, ENTITY_SENSOR,
    ENTITY_SWITCH, ENTITY_TEXT_SENSOR, ENTITY_INTEGRATION_SENSOR,
    ENTITY_BITMASK_SENSOR,
    REG_TYPE_COIL, REG_TYPE_DISCRETE, REG_TYPE_HOLDING, REG_TYPE_INPUT,
)

_LOGGER = logging.getLogger(__name__)

ESPHOME_DATA_TYPE = {
    DATA_TYPE_INT16: "S_WORD",
    DATA_TYPE_UINT16: "U_WORD",
    DATA_TYPE_INT32: "S_DWORD",
    DATA_TYPE_UINT32: "U_DWORD",
    DATA_TYPE_FLOAT32: "FP32",
    DATA_TYPE_INT64: "S_QWORD",
    DATA_TYPE_UINT64: "U_QWORD",
}

ESPHOME_REG_TYPE = {
    REG_TYPE_HOLDING: "holding",
    REG_TYPE_INPUT: "read",
    REG_TYPE_COIL: "coil",
    REG_TYPE_DISCRETE: "discrete_input",
}


class ESPHomeYAMLGenerator:
    """Generate ESPHome YAML from device config."""

    @staticmethod
    def generate(device_config: Dict[str, Any]) -> Dict[str, Any]:
        device_id = (
            device_config.get("id")
            or device_config.get("name", "device").lower().replace(" ", "_")
        )

        config: Dict[str, Any] = {
            "_device_id": device_id,
            "_device_config": device_config,
        }

        ESPHomeYAMLGenerator._add_entities(config, device_config)
        return config

    # ─────────────────────────────────────────────────────────────────────────
    # Entity routing
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _add_entities(config: Dict[str, Any], device_config: Dict[str, Any]) -> None:
        device_id = config["_device_id"]
        registers = device_config.get("registers", [])

        sensors: List[Dict] = []
        binary_sensors: List[Dict] = []
        numbers: List[Dict] = []
        switches: List[Dict] = []
        selects: List[Dict] = []
        text_sensors: List[Dict] = []
        integrations: List[Dict] = []
        globals_list: List[Dict] = list(device_config.get("globals", []))

        for reg in registers:
            et = reg.get("entity_type", ENTITY_SENSOR)

            if et == ENTITY_SENSOR:
                sensors.append(ESPHomeYAMLGenerator._make_sensor(reg, device_id))

            elif et == ENTITY_BINARY_SENSOR:
                binary_sensors.append(ESPHomeYAMLGenerator._make_binary_sensor(reg, device_id))

            elif et == ENTITY_NUMBER:
                numbers.append(ESPHomeYAMLGenerator._make_number(reg, device_id))

            elif et == ENTITY_SWITCH:
                switches.append(ESPHomeYAMLGenerator._make_switch(reg, device_id))

            elif et == ENTITY_SELECT:
                selects.append(ESPHomeYAMLGenerator._make_select(reg, device_id))

            elif et == ENTITY_TEXT_SENSOR:
                text_sensors.append(ESPHomeYAMLGenerator._make_text_sensor(reg, device_id))

            elif et == ENTITY_INTEGRATION_SENSOR:
                integrations.append(ESPHomeYAMLGenerator._make_integration_sensor(reg, device_id))

            elif et == ENTITY_BITMASK_SENSOR:
                # Creates an internal sensor + a linked text_sensor
                internal_sensor, linked_text = ESPHomeYAMLGenerator._make_bitmask_pair(reg, device_id)
                sensors.append(internal_sensor)
                if linked_text:
                    text_sensors.append(linked_text)

        # Extras (from template or device config)
        extras = device_config.get("extras", {})
        if extras.get("esp_status_sensor"):
            binary_sensors.append({"_type": "status", "name": "ESP Status"})
        if extras.get("restart_switch"):
            switches.append({"_type": "restart", "name": "Restart ESP"})
        if extras.get("esp_ip_sensor"):
            text_sensors.append({"_type": "ethernet_info", "name": "IP Adresa ESP"})

        config["sensors"] = sensors
        config["binary_sensors"] = binary_sensors
        config["numbers"] = numbers
        config["switches"] = switches
        config["selects"] = selects
        config["text_sensors"] = text_sensors
        config["integrations"] = integrations
        config["globals"] = globals_list

    # ─────────────────────────────────────────────────────────────────────────
    # Entity builders
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _sensor_base(reg: Dict, device_id: str) -> Dict:
        reg_id = reg.get("id") or reg.get("name", "sensor")
        return {
            "platform": "modbus_controller",
            "modbus_controller_id": f"{device_id}_modbus",
            "name": reg["friendly_name"],
            "id": reg_id,
            "address": reg["register"],
            "register_type": ESPHOME_REG_TYPE.get(reg.get("register_type", REG_TYPE_HOLDING), "holding"),
            "value_type": ESPHOME_DATA_TYPE.get(reg.get("data_type", DATA_TYPE_UINT16), "U_WORD"),
        }

    @staticmethod
    def _make_sensor(reg: Dict, device_id: str) -> Dict:
        s = ESPHomeYAMLGenerator._sensor_base(reg, device_id)
        if reg.get("internal"):
            s["internal"] = True
        for k in ["unit_of_measurement", "device_class", "state_class", "accuracy_decimals", "icon"]:
            src = {"unit_of_measurement": "unit"}.get(k, k)
            if reg.get(src) is not None:
                s[k] = reg[src]
        # Filters
        filters = ESPHomeYAMLGenerator._build_filters(reg)
        if filters:
            s["filters"] = filters
        return s

    @staticmethod
    def _make_binary_sensor(reg: Dict, device_id: str) -> Dict:
        if reg.get("_type") == "status":
            return {"_type": "status", "name": reg["name"]}
        reg_id = reg.get("id") or reg.get("name", "bs")
        s = {
            "platform": "modbus_controller",
            "modbus_controller_id": f"{device_id}_modbus",
            "name": reg["friendly_name"],
            "id": reg_id,
            "address": reg["register"],
            "register_type": ESPHOME_REG_TYPE.get(reg.get("register_type", REG_TYPE_HOLDING), "holding"),
        }
        if "bitmask" in reg:
            s["bitmask"] = reg["bitmask"]
        if "device_class" in reg:
            s["device_class"] = reg["device_class"]
        if reg.get("icon"):
            s["icon"] = reg["icon"]
        return s

    @staticmethod
    def _make_number(reg: Dict, device_id: str) -> Dict:
        reg_id = reg.get("id") or reg.get("name", "num")
        n = {
            "platform": "modbus_controller",
            "modbus_controller_id": f"{device_id}_modbus",
            "name": reg["friendly_name"],
            "id": reg_id,
            "address": reg["register"],
            "value_type": ESPHOME_DATA_TYPE.get(reg.get("data_type", DATA_TYPE_INT16), "S_WORD"),
            "multiply": reg.get("scale", 1.0),
        }
        if "min" in reg:
            n["min_value"] = reg["min"]
        if "max" in reg:
            n["max_value"] = reg["max"]
        if "step" in reg:
            n["step"] = reg["step"]
        if "unit" in reg:
            n["unit_of_measurement"] = reg["unit"]
        if "device_class" in reg:
            n["device_class"] = reg["device_class"]
        if "icon" in reg:
            n["icon"] = reg["icon"]
        return n

    @staticmethod
    def _make_switch(reg: Dict, device_id: str) -> Dict:
        if reg.get("_type") == "restart":
            return {"_type": "restart", "name": reg["name"]}
        reg_id = reg.get("id") or reg.get("name", "sw")
        return {
            "platform": "modbus_controller",
            "modbus_controller_id": f"{device_id}_modbus",
            "name": reg["friendly_name"],
            "id": reg_id,
            "address": reg["register"],
            "register_type": "coil",
        }

    @staticmethod
    def _make_select(reg: Dict, device_id: str) -> Dict:
        reg_id = reg.get("id") or reg.get("name", "sel")
        s = {
            "platform": "modbus_controller",
            "modbus_controller_id": f"{device_id}_modbus",
            "name": reg["friendly_name"],
            "id": reg_id,
            "address": reg["register"],
            "value_type": ESPHOME_DATA_TYPE.get(reg.get("data_type", DATA_TYPE_UINT16), "U_WORD"),
        }
        # Options map
        if "options_map" in reg:
            raw = reg["options_map"]
            if isinstance(raw, str):
                try:
                    s["optionsmap"] = json.loads(raw)
                except Exception:
                    s["optionsmap"] = {}
            elif isinstance(raw, dict):
                s["optionsmap"] = raw
        # Optional lambdas
        if reg.get("select_lambda"):
            s["lambda"] = reg["select_lambda"]
        if reg.get("select_write_lambda"):
            s["write_lambda"] = reg["select_write_lambda"]
        return s

    @staticmethod
    def _make_text_sensor(reg: Dict, device_id: str) -> Dict:
        if reg.get("_type") == "ethernet_info":
            return {"_type": "ethernet_info", "name": reg["name"]}
        reg_id = reg.get("id") or reg.get("name", "ts")
        ts: Dict[str, Any] = {
            "platform": "template",
            "name": reg["friendly_name"],
            "id": reg_id,
        }
        if reg.get("update_interval"):
            ts["update_interval"] = reg["update_interval"]
        if reg.get("lambda"):
            ts["lambda"] = reg["lambda"]
        if reg.get("icon"):
            ts["icon"] = reg["icon"]
        return ts

    @staticmethod
    def _make_integration_sensor(reg: Dict, device_id: str) -> Dict:
        reg_id = reg.get("id") or reg.get("name", "integ")
        s = {
            "platform": "integration",
            "name": reg["friendly_name"],
            "id": reg_id,
            "sensor": reg.get("integration_source", ""),
            "time_unit": reg.get("integration_time_unit", "h"),
        }
        if "unit" in reg:
            s["unit_of_measurement"] = reg["unit"]
        if "device_class" in reg:
            s["device_class"] = reg["device_class"]
        if "state_class" in reg:
            s["state_class"] = reg["state_class"]
        if "accuracy_decimals" in reg:
            s["accuracy_decimals"] = reg["accuracy_decimals"]
        s["restore"] = reg.get("restore", True)
        return s

    @staticmethod
    def _make_bitmask_pair(reg: Dict, device_id: str):
        """Create (internal_sensor, optional_text_sensor) for a bitmask register."""
        reg_id = reg.get("id") or reg.get("name", "bitmask_sensor")
        # Internal sensor that reads the raw value
        internal = {
            "platform": "modbus_controller",
            "modbus_controller_id": f"{device_id}_modbus",
            "name": reg.get("friendly_name", reg_id),
            "id": reg_id,
            "address": reg["register"],
            "register_type": ESPHOME_REG_TYPE.get(reg.get("register_type", REG_TYPE_HOLDING), "holding"),
            "value_type": ESPHOME_DATA_TYPE.get(reg.get("data_type", DATA_TYPE_UINT16), "U_WORD"),
            "internal": reg.get("internal", True),
        }
        if "bitmask" in reg:
            internal["bitmask"] = reg["bitmask"]
        # Build on_value action that publishes to linked text sensor
        text_sensor_id = reg.get("text_sensor_id")
        if text_sensor_id:
            true_text = reg.get("true_text", "Áno")
            false_text = reg.get("false_text", "Nie")
            internal["on_value"] = {
                "then": [{
                    "lambda": f'if (x) id({text_sensor_id}).publish_state("{true_text}");\nelse id({text_sensor_id}).publish_state("{false_text}");'
                }]
            }
            # Linked text sensor
            ts = {
                "platform": "template",
                "name": reg.get("text_sensor_name", text_sensor_id),
                "id": text_sensor_id,
            }
            if reg.get("icon"):
                ts["icon"] = reg["icon"]
            return internal, ts
        return internal, None

    @staticmethod
    def _build_filters(reg: Dict) -> List:
        if "custom_filters" in reg and reg["custom_filters"]:
            try:
                import yaml as _yaml
                parsed = _yaml.safe_load(reg["custom_filters"])
                if isinstance(parsed, list):
                    return parsed
            except Exception as e:
                _LOGGER.warning("Cannot parse custom_filters for %s: %s", reg.get("name"), e)
        filters = []
        scale = reg.get("scale")
        if scale and scale != 1.0:
            filters.append({"multiply": float(scale)})
        offset = reg.get("offset")
        if offset and offset != 0:
            filters.append({"offset": float(offset)})
        return filters

    # ─────────────────────────────────────────────────────────────────────────
    # YAML writer
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    async def write_to_file(config: Dict[str, Any], file_path: Path) -> None:
        device_config = config["_device_config"]
        device_id = config["_device_id"]
        conn = device_config.get("connection_params", {})
        extras = device_config.get("extras", {})
        send_wait = extras.get("modbus_send_wait_time", "200ms")

        L = []

        def nl():
            L.append("")

        def line(s=""):
            L.append(s)

        # ── Header ──────────────────────────────────────────────────────────
        L += [
            "# Auto-generated by Heat Pump Configurator v0.2",
            f"# Device: {device_id}",
            "# DO NOT EDIT MANUALLY - Use Heat Pump Configurator UI",
            "",
            "esphome:",
            f"  name: {device_id.replace('_', '-')}",
            f"  platform: {conn.get('platform', 'ESP32')}",
            f"  board: {conn.get('board', 'esp32dev')}",
            "",
            "logger:",
            "",
            "api:",
            "  encryption:",
            "    key: !secret api_encryption_key",
            "",
            "ota:",
            "  - platform: esphome",
            "    password: !secret ota_password",
            "",
            "wifi:",
            "  ssid: !secret wifi_ssid",
            "  password: !secret wifi_password",
            "",
        ]

        # ── UART ────────────────────────────────────────────────────────────
        L += [
            "uart:",
            f"  tx_pin: {conn.get('tx_pin', 'GPIO17')}",
            f"  rx_pin: {conn.get('rx_pin', 'GPIO16')}",
            f"  baud_rate: {conn.get('baudrate', 9600)}",
            f"  stop_bits: {conn.get('stop_bits', 1)}",
        ]
        parity = conn.get("parity", "NONE")
        if parity and parity != "NONE":
            L.append(f"  parity: {parity}")
        nl()

        # ── Modbus ──────────────────────────────────────────────────────────
        L += [
            "modbus:",
            f"  id: modbus1",
            f"  send_wait_time: {send_wait}",
            "",
            "modbus_controller:",
            f"  - id: {device_id}_modbus",
            f"    address: {conn.get('slave', 1)}",
            "    modbus_id: modbus1",
            "    setup_priority: -10",
            f"    update_interval: {device_config.get('scan_interval', 30)}s",
            "",
        ]

        # ── Globals ──────────────────────────────────────────────────────────
        globals_list = config.get("globals", [])
        if globals_list:
            L.append("globals:")
            for g in globals_list:
                L.append(f"  - id: {g['id']}")
                L.append(f"    type: {g.get('type', 'float')}")
                if "initial_value" in g:
                    L.append(f"    initial_value: '{g['initial_value']}'")
                if g.get("restore_value"):
                    L.append("    restore_value: yes")
            nl()

        # ── Sensors ──────────────────────────────────────────────────────────
        sensors = config.get("sensors", [])
        integrations = config.get("integrations", [])
        all_sensors = sensors + integrations
        if all_sensors:
            L.append("sensor:")
            for s in all_sensors:
                if s.get("platform") == "integration":
                    L.append(f"  - platform: integration")
                    L.append(f'    name: "{s["name"]}"')
                    L.append(f"    id: {s['id']}")
                    L.append(f"    sensor: {s['sensor']}")
                    L.append(f"    time_unit: {s['time_unit']}")
                    for f in ["unit_of_measurement", "device_class", "state_class", "accuracy_decimals"]:
                        if f in s:
                            L.append(f"    {f}: {ESPHomeYAMLGenerator._q(s[f], f)}")
                    L.append(f"    restore: {str(s.get('restore', True)).lower()}")
                    nl()
                else:
                    ESPHomeYAMLGenerator._write_modbus_sensor(L, s)
            nl()

        # ── Binary sensors ───────────────────────────────────────────────────
        bsensors = config.get("binary_sensors", [])
        if bsensors:
            L.append("binary_sensor:")
            for bs in bsensors:
                if bs.get("_type") == "status":
                    L.append("  - platform: status")
                    L.append(f'    name: "{bs["name"]}"')
                    nl()
                else:
                    L.append("  - platform: modbus_controller")
                    L.append(f"    modbus_controller_id: {bs['modbus_controller_id']}")
                    L.append(f'    name: "{bs["name"]}"')
                    L.append(f"    id: {bs['id']}")
                    L.append(f"    address: 0x{bs['address']:04X}")
                    L.append(f"    register_type: {bs['register_type']}")
                    if "bitmask" in bs:
                        L.append(f"    bitmask: {bs['bitmask']}")
                    if "device_class" in bs:
                        L.append(f"    device_class: {bs['device_class']}")
                    if "icon" in bs:
                        L.append(f"    icon: {bs['icon']}")
                    nl()
            nl()

        # ── Numbers ──────────────────────────────────────────────────────────
        numbers = config.get("numbers", [])
        if numbers:
            L.append("number:")
            for n in numbers:
                L.append("  - platform: modbus_controller")
                L.append(f"    modbus_controller_id: {n['modbus_controller_id']}")
                L.append(f'    name: "{n["name"]}"')
                L.append(f"    id: {n['id']}")
                L.append(f"    address: 0x{n['address']:04X}")
                L.append(f"    value_type: {n['value_type']}")
                L.append(f"    multiply: {n.get('multiply', 1.0)}")
                for f in ["min_value", "max_value", "step", "unit_of_measurement", "device_class", "icon"]:
                    if f in n:
                        L.append(f"    {f}: {ESPHomeYAMLGenerator._q(n[f], f)}")
                nl()
            nl()

        # ── Switches ─────────────────────────────────────────────────────────
        switches = config.get("switches", [])
        if switches:
            L.append("switch:")
            for sw in switches:
                if sw.get("_type") == "restart":
                    L.append("  - platform: restart")
                    L.append(f'    name: "{sw["name"]}"')
                    nl()
                else:
                    L.append("  - platform: modbus_controller")
                    L.append(f"    modbus_controller_id: {sw['modbus_controller_id']}")
                    L.append(f'    name: "{sw["name"]}"')
                    L.append(f"    id: {sw['id']}")
                    L.append(f"    address: 0x{sw['address']:04X}")
                    L.append(f"    register_type: {sw['register_type']}")
                    nl()
            nl()

        # ── Selects ──────────────────────────────────────────────────────────
        selects = config.get("selects", [])
        if selects:
            L.append("select:")
            for sel in selects:
                L.append("  - platform: modbus_controller")
                L.append(f"    modbus_controller_id: {sel['modbus_controller_id']}")
                L.append(f'    name: "{sel["name"]}"')
                L.append(f"    id: {sel['id']}")
                L.append(f"    address: 0x{sel['address']:04X}")
                if "value_type" in sel:
                    L.append(f"    value_type: {sel['value_type']}")
                if "optionsmap" in sel:
                    L.append("    optionsmap:")
                    for k, v in sel["optionsmap"].items():
                        L.append(f'      "{k}": {v}')
                if "lambda" in sel:
                    L.append("    lambda: |-")
                    for lline in sel["lambda"].split("\n"):
                        L.append(f"      {lline}")
                if "write_lambda" in sel:
                    L.append("    write_lambda: |-")
                    for lline in sel["write_lambda"].split("\n"):
                        L.append(f"      {lline}")
                nl()
            nl()

        # ── Text sensors ─────────────────────────────────────────────────────
        text_sensors = config.get("text_sensors", [])
        if text_sensors:
            L.append("text_sensor:")
            for ts in text_sensors:
                if ts.get("_type") == "ethernet_info":
                    L.append("  - platform: ethernet_info")
                    L.append("    ip_address:")
                    L.append(f'      name: "{ts["name"]}"')
                    nl()
                else:
                    L.append("  - platform: template")
                    L.append(f'    name: "{ts["name"]}"')
                    L.append(f"    id: {ts['id']}")
                    if "update_interval" in ts:
                        L.append(f"    update_interval: {ts['update_interval']}")
                    if "icon" in ts:
                        L.append(f"    icon: {ts['icon']}")
                    if "lambda" in ts:
                        L.append("    lambda: |-")
                        for lline in ts["lambda"].split("\n"):
                            L.append(f"      {lline}")
                    nl()
            nl()

        content = "\n".join(L)

        def _write():
            file_path.write_text(content, encoding="utf-8")

        await asyncio.get_running_loop().run_in_executor(None, _write)

    @staticmethod
    def _write_modbus_sensor(L: List, s: Dict) -> None:
        """Write a single modbus_controller sensor block."""
        L.append("  - platform: modbus_controller")
        L.append(f"    modbus_controller_id: {s['modbus_controller_id']}")
        L.append(f'    name: "{s["name"]}"')
        L.append(f"    id: {s['id']}")
        L.append(f"    address: 0x{s['address']:04X}")
        L.append(f"    register_type: {s['register_type']}")
        L.append(f"    value_type: {s['value_type']}")
        if s.get("internal"):
            L.append("    internal: true")
        if "bitmask" in s:
            L.append(f"    bitmask: {s['bitmask']}")
        for f in ["unit_of_measurement", "device_class", "state_class", "accuracy_decimals", "icon"]:
            if f in s:
                L.append(f"    {f}: {ESPHomeYAMLGenerator._q(s[f], f)}")
        if "filters" in s and s["filters"]:
            L.append("    filters:")
            for fi in s["filters"]:
                if isinstance(fi, dict):
                    for fk, fv in fi.items():
                        if isinstance(fv, dict):
                            L.append(f"      - {fk}:")
                            for sk, sv in fv.items():
                                L.append(f"          {sk}: {sv}")
                        elif isinstance(fv, str) and "\n" in fv:
                            L.append(f"      - {fk}: |-")
                            for fl in fv.split("\n"):
                                L.append(f"          {fl}")
                        else:
                            L.append(f"      - {fk}: {fv}")
                else:
                    L.append(f"      - {fi}")
        # on_value action (used by bitmask sensors)
        if "on_value" in s:
            ov = s["on_value"]
            L.append("    on_value:")
            L.append("      then:")
            for action in ov.get("then", []):
                if "lambda" in action:
                    L.append("        - lambda: |-")
                    for ll in action["lambda"].split("\n"):
                        L.append(f"            {ll}")
        ESPHomeYAMLGenerator._nl(L)

    @staticmethod
    def _q(value: Any, field: str) -> str:
        """Quote string values for YAML where needed."""
        if not isinstance(value, str):
            return str(value)
        needs_quote = ["unit_of_measurement", "name"]
        if field in needs_quote or any(c in value for c in ['°', ' ', ':', '#']):
            return f'"{value}"'
        return value

    @staticmethod
    def _nl(L: List) -> None:
        L.append("")