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
    ENTITY_CLIMATE,
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
    """Generate Modbus YAML configuration from device config.

    Supported HA Modbus entity types:
      - sensor        : read-only value from holding/input register
      - binary_sensor : ON/OFF from coil or discrete_input register
      - switch        : read+write coil or holding register (on/off)
      - climate       : thermostat — reads current temp, writes target temp + HVAC mode

    NOT supported in HA Modbus (ESPHome-only):
      - number, select, text_sensor, integration_sensor, bitmask_sensor

    For bitmask registers (holding register with packed bits):
      Use entity_type=sensor to read the raw uint16 value, then create
      Template binary_sensors in HA configuration.yaml to extract individual bits.
    """

    @staticmethod
    def generate(device_config: Dict[str, Any]) -> Dict[str, Any]:
        connection_type = device_config.get("connection_type")
        device_id = (
            device_config.get("file_id")
            or device_config.get("name", "device").lower().replace(" ", "_")
        )

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
        params = device_config["connection_params"]
        config = {
            "name": device_id,
            "type": "serial",
            "port": params["port"],
            "baudrate": params.get("baudrate", 9600),
            "bytesize": params.get("bytesize", 8),
            "method": "rtu",
            "parity": params.get("parity", "N"),
            "stopbits": params.get("stop_bits", 1),
        }
        ModbusYAMLGenerator._add_entities(config, device_config, device_id)
        return config

    @staticmethod
    def _add_entities(
        config: Dict[str, Any], device_config: Dict[str, Any], device_id: str
    ) -> None:
        registers = device_config.get("registers", [])
        slave = device_config["connection_params"].get("slave", 1)
        scan_interval = device_config.get("scan_interval", 30)

        sensors: List[Dict] = []
        binary_sensors: List[Dict] = []
        switches: List[Dict] = []
        climates: List[Dict] = []

        for register in registers:
            entity_type = register.get("entity_type", ENTITY_SENSOR)
            if entity_type == ENTITY_SENSOR:
                sensors.append(
                    ModbusYAMLGenerator._make_sensor(register, device_config, device_id, slave, scan_interval)
                )
            elif entity_type == ENTITY_BINARY_SENSOR:
                binary_sensors.append(
                    ModbusYAMLGenerator._make_binary_sensor(register, device_config, device_id, slave, scan_interval)
                )
            elif entity_type == ENTITY_SWITCH:
                switches.append(
                    ModbusYAMLGenerator._make_switch(register, device_config, device_id, slave, scan_interval)
                )
            elif entity_type == ENTITY_CLIMATE:
                climates.append(
                    ModbusYAMLGenerator._make_climate(register, device_config, device_id, slave, scan_interval)
                )
            else:
                _LOGGER.warning(
                    "Entity type '%s' is not supported in HA Modbus, skipping register '%s'. "
                    "Use ESPHome connection type for number/select/bitmask entities.",
                    entity_type,
                    register.get("name", "unknown"),
                )

        if sensors:
            config["sensors"] = sensors
        if binary_sensors:
            config["binary_sensors"] = binary_sensors
        if switches:
            config["switches"] = switches
        if climates:
            config["climates"] = climates

    @staticmethod
    def _base_entity(register, device_config, device_id, slave, scan_interval):
        device_name = device_config.get("name", "Device")
        reg_id = register.get("id") or register.get("name", "reg").lower().replace(" ", "_")
        return {
            "name": " ".join(f"{device_name} {register['friendly_name']}".split()),
            "unique_id": f"{device_id}_{reg_id}",
            "address": register["register"],
            "slave": slave,
            "scan_interval": register.get("scan_interval", scan_interval),
        }

    @staticmethod
    def _make_sensor(register, device_config, device_id, slave, scan_interval):
        """Read-only sensor from holding or input register.

        Supports: uint16, int16, uint32, int32, float32, int64, uint64
        Scale/offset/precision for unit conversion.
        """
        s = ModbusYAMLGenerator._base_entity(register, device_config, device_id, slave, scan_interval)
        reg_type = register.get("register_type", REG_TYPE_HOLDING)
        s["input_type"] = "input" if reg_type == REG_TYPE_INPUT else "holding"
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
        """Binary sensor from coil or discrete_input register (ON/OFF only).

        For bitmask registers (holding register with packed bits):
        Use entity_type=sensor instead, then add Template binary_sensors
        in HA configuration.yaml using Jinja2 bitwise operations.

        Example template:
          template:
            - binary_sensor:
                - name: "SG Signal"
                  state: "{{ (states('sensor.device_stav_prepinaca') | int) & 0x01 > 0 }}"
        """
        s = ModbusYAMLGenerator._base_entity(register, device_config, device_id, slave, scan_interval)
        reg_type = register.get("register_type", REG_TYPE_COIL)
        if reg_type == REG_TYPE_DISCRETE:
            s["input_type"] = "discrete_input"
        elif reg_type == REG_TYPE_HOLDING:
            # holding register used as binary — reads 0/1 value, no bitmask support in HA Modbus
            s["input_type"] = "holding"
        else:
            s["input_type"] = "coil"
        if "device_class" in register:
            s["device_class"] = register["device_class"]
        return s

    @staticmethod
    def _make_switch(register, device_config, device_id, slave, scan_interval):
        """Read + write switch via coil or holding register.

        For coil: write_type: coil  (writes 0/1 to coil address)
        For holding register: write_type: holding  (writes command_on/command_off value)

        Supports verify block to confirm state after write.
        """
        s = ModbusYAMLGenerator._base_entity(register, device_config, device_id, slave, scan_interval)
        reg_type = register.get("register_type", REG_TYPE_COIL)
        if reg_type == REG_TYPE_HOLDING:
            s["write_type"] = "holding"
        else:
            s["write_type"] = "coil"
        # Optional: custom on/off values for holding register switches
        if "command_on" in register:
            s["command_on"] = register["command_on"]
        if "command_off" in register:
            s["command_off"] = register["command_off"]
        if "state_on" in register:
            s["state_on"] = register["state_on"]
        if "state_off" in register:
            s["state_off"] = register["state_off"]
        # Optional verify block
        if register.get("verify_address") is not None:
            s["verify"] = {
                "address": register["verify_address"],
                "input_type": register.get("verify_input_type", "holding"),
                "delay": register.get("verify_delay", 0),
            }
            if "state_on" in register:
                s["verify"]["state_on"] = register["state_on"]
            if "state_off" in register:
                s["verify"]["state_off"] = register["state_off"]
        return s

    @staticmethod
    def _make_climate(register, device_config, device_id, slave, scan_interval):
        """Climate entity for thermostat-style RW temperature control.

        Reads current temperature from 'register' (address field).
        Writes target temperature to 'target_temp_register'.
        Optionally reads/writes HVAC mode via 'hvac_mode_register'.
        Optionally controls on/off via 'hvac_onoff_register' or 'hvac_onoff_coil'.

        Required register fields:
          - register: address of current temperature register
          - target_temp_register: address to write setpoint
          - min_temp, max_temp: allowed range
          - scale: e.g. 0.1 for n*0.1°C registers

        Optional:
          - hvac_mode_register + hvac_mode_values: dict mapping HA modes to register values
            e.g. {"state_heat": 1, "state_cool": 2, "state_off": 0}
          - hvac_onoff_register: address for on/off (0=off, 1=on)
          - temp_step: setpoint step size (default 0.5)
        """
        c = ModbusYAMLGenerator._base_entity(register, device_config, device_id, slave, scan_interval)
        reg_type = register.get("register_type", REG_TYPE_HOLDING)
        c["input_type"] = "input" if reg_type == REG_TYPE_INPUT else "holding"
        c["data_type"] = DATA_TYPE_MAPPING.get(register.get("data_type", DATA_TYPE_INT16), "int16")

        for k in ["scale", "offset", "precision", "min_temp", "max_temp"]:
            if k in register:
                c[k] = register[k]

        c["target_temp_register"] = register.get("target_temp_register", register["register"])
        c["target_temp_write_registers"] = register.get("target_temp_write_registers", False)
        c["temp_step"] = register.get("temp_step", 1)
        c["temperature_unit"] = register.get("temperature_unit", "C")

        # Optional HVAC mode register
        if "hvac_mode_register" in register:
            hvac_values = register.get("hvac_mode_values", {})
            c["hvac_mode_register"] = {
                "address": register["hvac_mode_register"],
                "write_registers": register.get("hvac_mode_write_registers", False),
                "values": hvac_values,
            }

        # Optional on/off register (when on/off is separate from HVAC mode)
        if "hvac_onoff_register" in register:
            c["hvac_onoff_register"] = register["hvac_onoff_register"]
            if "hvac_on_value" in register:
                c["hvac_on_value"] = register["hvac_on_value"]
            if "hvac_off_value" in register:
                c["hvac_off_value"] = register["hvac_off_value"]

        return c

    # Fields that should be rendered as hex (0xABCD)
    _HEX_FIELDS = {"address", "target_temp_register", "hvac_onoff_register",
                   "hvac_on_value", "hvac_off_value"}

    # Bare YAML values that would be misinterpreted without quotes
    _UNSAFE_BARE = {
        "%", "s", "C", "F", "N", "E", "O",
        "y", "n", "on", "off", "yes", "no", "true", "false", "null", "~",
    }

    @staticmethod
    def _yaml_value(key: str, value) -> str:
        """Render a scalar value correctly for YAML output."""
        if key in ModbusYAMLGenerator._HEX_FIELDS and isinstance(value, int):
            return f"0x{value:04X}"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            needs_quote = (
                key in ("name", "unit_of_measurement")
                or value in ModbusYAMLGenerator._UNSAFE_BARE
                or any(c in value for c in (":", "#", "{", "}", "[", "]", ",", "%", "°", "\n", '"'))
                or value == ""
            )
            if needs_quote:
                escaped = value.replace('"', '\\"')
                return f'"{escaped}"'
            return value
        return str(value)

    @staticmethod
    def _write_entity(lines: List[str], entity: Dict[str, Any], indent: int = 6) -> None:
        """Write a single entity dict as YAML lines."""
        pad = " " * indent
        first = True
        for key, value in entity.items():
            prefix = f"{' ' * (indent - 2)}- " if first else pad
            first = False
            if isinstance(value, dict):
                lines.append(f"{prefix}{key}:")
                for dk, dv in value.items():
                    lines.append(f"{pad}  {dk}: {ModbusYAMLGenerator._yaml_value(dk, dv)}")
            else:
                lines.append(f"{prefix}{key}: {ModbusYAMLGenerator._yaml_value(key, value)}")

    @staticmethod
    async def write_to_file(config: Dict[str, Any], file_path: Path) -> None:
        lines = [
            "# Auto-generated by ProtoConfig v0.2",
            f"# Device: {config.get('name', 'Unknown')}",
            "# DO NOT EDIT MANUALLY - Use ProtoConfig UI",
            "",
            f"- name: {config['name']}",
            f"  type: {config['type']}",
        ]

        if config["type"] == "tcp":
            lines += [
                f"  host: {config['host']}",
                f"  port: {config['port']}",
            ]
        elif config["type"] == "serial":
            for k in ["port", "baudrate", "bytesize", "method", "parity", "stopbits"]:
                if k in config:
                    lines.append(f"  {k}: {config[k]}")

        for section in ["sensors", "binary_sensors", "switches", "climates"]:
            entities = config.get(section)
            if not entities:
                continue
            lines.append(f"\n  {section}:")
            for entity in entities:
                ModbusYAMLGenerator._write_entity(lines, entity, indent=6)
                lines.append("")

        content = "\n".join(lines) + "\n"

        def _write():
            file_path.write_text(content, encoding="utf-8")

        await asyncio.get_running_loop().run_in_executor(None, _write)