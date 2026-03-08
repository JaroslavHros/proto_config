"""Constants for ProtoConfig."""

DOMAIN = "proto_config"

# Configuration keys
CONF_CONNECTION_TYPE = "connection_type"
CONF_DEVICE_NAME = "device_name"
CONF_MODBUS_HOST = "modbus_host"
CONF_MODBUS_PORT = "modbus_port"
CONF_MODBUS_SLAVE = "modbus_slave"
CONF_REGISTERS = "registers"
CONF_SCAN_INTERVAL = "scan_interval"

# Connection types
CONN_MODBUS_TCP = "modbus_tcp"
CONN_MODBUS_RTU = "modbus_rtu"
CONN_ESPHOME = "esphome"

CONNECTION_TYPES = [
    CONN_MODBUS_TCP,
    CONN_MODBUS_RTU,
    CONN_ESPHOME,
]

# Register types
REG_TYPE_HOLDING = "holding"
REG_TYPE_INPUT = "input"
REG_TYPE_COIL = "coil"
REG_TYPE_DISCRETE = "discrete_input"

REGISTER_TYPES = [
    REG_TYPE_HOLDING,
    REG_TYPE_INPUT,
    REG_TYPE_COIL,
    REG_TYPE_DISCRETE,
]

# Data types
DATA_TYPE_INT16 = "int16"
DATA_TYPE_UINT16 = "uint16"
DATA_TYPE_INT32 = "int32"
DATA_TYPE_UINT32 = "uint32"
DATA_TYPE_FLOAT32 = "float32"
DATA_TYPE_INT64 = "int64"
DATA_TYPE_UINT64 = "uint64"

DATA_TYPES = [
    DATA_TYPE_INT16,
    DATA_TYPE_UINT16,
    DATA_TYPE_INT32,
    DATA_TYPE_UINT32,
    DATA_TYPE_FLOAT32,
    DATA_TYPE_INT64,
    DATA_TYPE_UINT64,
]

# Entity types
ENTITY_SENSOR = "sensor"
ENTITY_BINARY_SENSOR = "binary_sensor"
ENTITY_SWITCH = "switch"
ENTITY_CLIMATE = "climate"

# ESPHome-only entity types
ENTITY_NUMBER = "number"
ENTITY_SELECT = "select"
ENTITY_TEXT_SENSOR = "text_sensor"
ENTITY_INTEGRATION_SENSOR = "integration_sensor"
ENTITY_BITMASK_SENSOR = "bitmask_sensor"

# Modbus supports: sensor, binary_sensor, switch, climate
# (+ cover, fan, light - not implemented yet)
ENTITY_TYPES_MODBUS = [
    ENTITY_SENSOR,
    ENTITY_BINARY_SENSOR,
    ENTITY_SWITCH,
    ENTITY_CLIMATE,
]

ENTITY_TYPES_ESPHOME = [
    ENTITY_SENSOR,
    ENTITY_BINARY_SENSOR,
    ENTITY_NUMBER,
    ENTITY_SWITCH,
    ENTITY_SELECT,
    ENTITY_TEXT_SENSOR,
    ENTITY_INTEGRATION_SENSOR,
    ENTITY_BITMASK_SENSOR,
]

# Device classes for sensors
DEVICE_CLASSES_SENSOR = [
    "temperature",
    "pressure",
    "power",
    "energy",
    "current",
    "voltage",
    "frequency",
    "power_factor",
    None,
]

# State classes
STATE_CLASSES = [
    "measurement",
    "total",
    "total_increasing",
    None,
]

# Default values
DEFAULT_MODBUS_PORT = 502
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_SLAVE_ID = 1

# ESPHome specific
CONF_ICON = "icon"
CONF_ACCURACY_DECIMALS = "accuracy_decimals"
CONF_FILTERS = "filters"
CONF_LAMBDA = "lambda"
CONF_UPDATE_INTERVAL = "update_interval"

# ESPHome Icons
ESPHOME_ICONS = [
    "mdi:thermometer",
    "mdi:thermometer-lines",
    "mdi:water-thermometer",
    "mdi:gauge",
    "mdi:flash",
    "mdi:lightning-bolt",
    "mdi:water-pump",
    "mdi:fan",
    "mdi:power",
    "mdi:counter",
    "mdi:engine",
    "mdi:pump",
    "mdi:valve",
    "mdi:radiator",
    "mdi:water-boiler",
    "mdi:snowflake",
    "mdi:fire",
    "mdi:toggle-switch",
    "mdi:alert",
    "mdi:alert-circle",
    None,
]

# Template names
TEMPLATE_GENERIC_HEATPUMP = "generic_heatpump"
TEMPLATE_ITHERMPUMP = "ithermpump"

TEMPLATES = {
    TEMPLATE_GENERIC_HEATPUMP: "Generic Heat Pump (ESPHome)",
    TEMPLATE_ITHERMPUMP: "iThermPump (ESPHome)",
}