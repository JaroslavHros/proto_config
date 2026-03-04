"""Modbus YAML configuration generator."""
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List

from ..const import (
    CONN_MODBUS_RTU,
    CONN_MODBUS_TCP,
    DATA_TYPE_FLOAT32,
    DATA_TYPE_INT16,
    DATA_TYPE_INT32,
    DATA_TYPE_INT64,
    DATA_TYPE_UINT16,
    DATA_TYPE_UINT32,
    DATA_TYPE_UINT64,
    ENTITY_BINARY_SENSOR,
    ENTITY_NUMBER,
    ENTITY_SELECT,
    ENTITY_SENSOR,
    ENTITY_SWITCH,
    REG_TYPE_COIL,
    REG_TYPE_DISCRETE,
    REG_TYPE_HOLDING,
    REG_TYPE_INPUT,
)

_LOGGER = logging.getLogger(__name__)

DATA_TYPE_MAPPING = {
    DATA_TYPE_INT16: "int16",
    DATA_TYPE_UINT16: "uint16",
    DATA_TYPE_INT32: "int32",
    DATA_TYPE_UINT32: "uint32",
    DATA_TYPE_FLOAT32: "float32",
    DATA_TYPE_INT64: "int64",
    DATA_TYPE_UINT64: "uint64",
}


class ModbusYAMLGenerator:
    """Generate Modbus YAML configuration from device config."""

    @staticmethod
    def generate(device_config: Dict[str, Any]) -> Dict[str, Any]:
        connection_type = device_config.get("connection_type")
        device_id = device_config.get("id") or device_config.get("name", "device").lower().replace(" ", "_")

        if connection_type == CONN_MODBUS_TCP:
            return ModbusYAMLGenerator._generate_tcp(device_config, device_id)
        elif connection_type == CONN_MODBUS_RTU:
            return ModbusYAMLGenerator._generate_rtu(device_config, device_id)
        else:
            raise ValueError(f"Unsupported connection type: {connection_type}")

    @staticmethod
    def _generate_tcp(device_config: Dict[str, Any], device_id: str) -> Dict[str, Any]:
        config = {
            "name": device_id,
            "type": "tcp",
            "host": device_config["connection_params"]["host"],
            "port": device_config["connection_params"].get("port", 502),
        }
        ModbusYAMLGenerator._add_entities(config, device_config, device_id)
        return config

    @staticmethod
    def _generate_rtu(device_config: Dict[str, Any], device_id: str) -> Dict[str, Any]:
        config = {
            "name": device_id,
            "type": "serial",
            "port": device_config["connection_params"]["port"],
            "baudrate": device_config["connection_params"].get("baudrate", 9600),
            "bytesize": device_config["connection_params"].get("bytesize", 8),
            "parity": device_config["connection_params"].get("parity", "N"),
            "stopbits": device_config["connection_params"].get("stop_bits", 1),
        }
        ModbusYAMLGenerator._add_entities(config, device_config, device_id)
        return config

    @staticmethod
    def _add_entities(config: Dict[str, Any], device_config: Dict[str, Any], device_id: str) -> None:
        registers = device_config.get("registers", [])
        slave = device_config["connection_params"].get("slave", 1)
        scan_interval = device_config.get("scan_interval", 30)

        sensors, binary_sensors, numbers, switches, selects = [], [], [], [], []

        for register in registers:
            entity_type = register.get("entity_type", ENTITY_SENSOR)
            if entity_type == ENTITY_SENSOR:
                sensors.append(ModbusYAMLGenerator._make_sensor(register, device_config, device_id, slave, scan_interval))
            elif entity_type == ENTITY_BINARY_SENSOR:
                binary_sensors.append(ModbusYAMLGenerator._make_binary_sensor(register, device_config, device_id, slave, scan_interval))
            elif entity_type == ENTITY_NUMBER:
                numbers.append(ModbusYAMLGenerator._make_number(register, device_config, device_id, slave, scan_interval))
            elif entity_type == ENTITY_SWITCH:
                switches.append(ModbusYAMLGenerator._make_switch(register, device_config, device_id, slave, scan_interval))
            elif entity_type == ENTITY_SELECT:
                selects.append(ModbusYAMLGenerator._make_select(register, device_config, device_id, slave, scan_interval))

        if sensors:
            config["sensors"] = sensors
        if binary_sensors:
            config["binary_sensors"] = binary_sensors
        if numbers:
            config["numbers"] = numbers  # FIXED: was "climates"
        if switches:
            config["switches"] = switches
        if selects:
            config["selects"] = selects

    @staticmethod
    def _base_entity(register, device_config, device_id, slave, scan_interval):
        device_name = device_config.get("name", "Device")
        reg_id = register.get("id") or register.get("name", "reg").lower().replace(" ", "_")
        return {
            "name": f"{device_name} {register['friendly_name']}",
            "unique_id": f"{device_id}_{reg_id}",
            "address": register["register"],
            "slave": slave,
            "scan_interval": register.get("scan_interval", scan_interval),
        }

    @staticmethod
    def _make_sensor(register, device_config, device_id, slave, scan_interval):
        s = ModbusYAMLGenerator._base_entity(register, device_config, device_id, slave, scan_interval)
        reg_type = register.get("register_type", REG_TYPE_HOLDING)
        if reg_type == REG_TYPE_INPUT:
            s["input_type"] = "input"
        else:
            s["input_type"] = "holding"
        s["data_type"] = DATA_TYPE_MAPPING.get(register.get("data_type", DATA_TYPE_INT16), "int16")
        for k in ["scale", "offset", "precision"]:
            if k in register:
                s[k] = register[k]
        if "unit" in register:
            s["unit_of_measurement"] = register["unit"]
        for k in ["device_class", "state_class"]:
            if k in register:
                s[k] = register[k]
        return s

    @staticmethod
    def _make_binary_sensor(register, device_config, device_id, slave, scan_interval):
        s = ModbusYAMLGenerator._base_entity(register, device_config, device_id, slave, scan_interval)
        reg_type = register.get("register_type", REG_TYPE_COIL)
        if reg_type == REG_TYPE_DISCRETE:
            s["input_type"] = "discrete_input"
        else:
            s["input_type"] = "coil"
        if "device_class" in register:
            s["device_class"] = register["device_class"]
        return s

    @staticmethod
    def _make_number(register, device_config, device_id, slave, scan_interval):
        n = ModbusYAMLGenerator._base_entity(register, device_config, device_id, slave, scan_interval)
        n["data_type"] = DATA_TYPE_MAPPING.get(register.get("data_type", DATA_TYPE_INT16), "int16")
        if "min" in register:
            n["min_value"] = register["min"]
        if "max" in register:
            n["max_value"] = register["max"]
        if "step" in register:
            n["step"] = register["step"]
        if "scale" in register:
            n["scale"] = register["scale"]
        return n

    @staticmethod
    def _make_switch(register, device_config, device_id, slave, scan_interval):
        s = ModbusYAMLGenerator._base_entity(register, device_config, device_id, slave, scan_interval)
        s["write_type"] = "coil"
        return s

    @staticmethod
    def _make_select(register, device_config, device_id, slave, scan_interval):
        s = ModbusYAMLGenerator._base_entity(register, device_config, device_id, slave, scan_interval)
        s["data_type"] = DATA_TYPE_MAPPING.get(register.get("data_type", DATA_TYPE_UINT16), "uint16")
        if "options_map" in register:
            import json
            try:
                s["options_map"] = json.loads(register["options_map"])
            except Exception:
                s["options_map"] = {}
        return s

    @staticmethod
    async def write_to_file(config: Dict[str, Any], file_path: Path) -> None:
        lines = [
            "# Auto-generated by Heat Pump Configurator v0.2",
            f"# Device: {config.get('name', 'Unknown')}",
            "# DO NOT EDIT MANUALLY - Use Heat Pump Configurator UI",
            "",
            f"- name: {config['name']}",
            f"  type: {config['type']}",
        ]

        if config["type"] == "tcp":
            lines += [f"  host: {config['host']}", f"  port: {config['port']}"]
        elif config["type"] == "serial":
            lines += [
                f"  port: {config['port']}",
                f"  baudrate: {config['baudrate']}",
                f"  bytesize: {config.get('bytesize', 8)}",
                f"  parity: {config.get('parity', 'N')}",
                f"  stopbits: {config.get('stopbits', 1)}",
            ]

        def write_entities(section_key, label):
            if section_key not in config or not config[section_key]:
                return
            lines.append(f"\n  {label}:")
            for e in config[section_key]:
                lines.append("    -")
                lines.append(f'      name: "{e["name"]}"')
                lines.append(f'      unique_id: {e["unique_id"]}')
                lines.append(f'      address: {e["address"]}')
                lines.append(f'      slave: {e["slave"]}')
                for field in ["input_type", "data_type", "scan_interval", "scale", "offset",
                               "precision", "device_class", "state_class", "write_type",
                               "min_value", "max_value", "step"]:
                    if field in e:
                        lines.append(f"      {field}: {e[field]}")
                if "unit_of_measurement" in e:
                    unit = e["unit_of_measurement"]
                    q = '"' if any(c in unit for c in ['°', ' ']) else ''
                    lines.append(f"      unit_of_measurement: {q}{unit}{q}")
                if "options_map" in e:
                    lines.append("      options_map:")
                    for opt_key, opt_val in e["options_map"].items():
                        lines.append(f'        "{opt_key}": {opt_val}')
                lines.append("")

        write_entities("sensors", "sensors")
        write_entities("binary_sensors", "binary_sensors")
        write_entities("numbers", "numbers")
        write_entities("switches", "switches")
        write_entities("selects", "selects")

        content = "\n".join(lines)

        def _write():
            file_path.write_text(content, encoding="utf-8")

        await asyncio.get_running_loop().run_in_executor(None, _write)
