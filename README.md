# ProtoConfig — Home Assistant Custom Integration

Generátor konfiguračných súborov pre Modbus a ESPHome zariadenia priamo z HA UI wizardu.

---

## Čo appka robí

ProtoConfig ti umožní nakonfigurovať ľubovoľné Modbus (TCP/RTU) alebo ESPHome zariadenie cez UI wizard bez toho, aby si musel ručne písať YAML. Po dokončení wizardu vygeneruje hotový YAML súbor do správneho priečinka HA.

---

## Podporované typy pripojenia

| Typ | Popis | Výstupný súbor |
|-----|-------|----------------|
| **Modbus RTU** | RS485 sériová linka | `/config/modbus/nazov_zariadenia.yaml` |
| **Modbus TCP** | Ethernet/WiFi Modbus | `/config/modbus/nazov_zariadenia.yaml` |
| **ESPHome** | ESP8266/ESP32 cez ESPHome | `/config/esphome/nazov_zariadenia.yaml` |

---

# Modbus entity typy

HA Modbus integrácia podporuje: `sensor`, `binary_sensor`, `switch`, `climate`.
Ostatné typy (`number`, `select`, `cover`, `fan`, `light`) nie sú implementované v ProtoConfig (zatiaľ).

---

## `sensor` — Senzor (len čítanie)

Číta hodnotu z **holding** alebo **input** registra.

**Parametre:**
- Adresa registra
- Register type: `holding` (default) / `input`
- Data type: `int16`, `uint16`, `int32`, `uint32`, `float32`, `int64`, `uint64`
- Scale (napr. `0.1` pre n×0.1°C), Precision, Jednotka, device_class, state_class

**Príklad výstupu:**
```yaml
sensors:
  - name: "iterm_tepelko Vstupná teplota vody"
    unique_id: iterm_tepelko_vstupna_teplota_vody
    address: 14
    slave: 1
    input_type: holding
    data_type: int16
    scale: 0.1
    precision: 1
    unit_of_measurement: "°C"
    device_class: temperature
    state_class: measurement
    scan_interval: 10
```

---

## `binary_sensor` — Binárny senzor (len čítanie)

Číta stav ON/OFF z **coil** alebo **discrete_input** registra.

> ⚠️ **HA Modbus binary_sensor nepodporuje bitmask ani holding registre.**
> Pre bitmaskové status registre (napr. `0x0002 Switch Status`) použi `sensor` (raw uint16)
> a v `configuration.yaml` si pridaj Template binary_sensors.

**Príklad výstupu (coil):**
```yaml
binary_sensors:
  - name: "iterm_tepelko Stav relé"
    address: 100
    slave: 1
    input_type: coil
    scan_interval: 15
```

**Ako riešiť bitmaskové holding registre:**

Krok 1 — v ProtoConfig pridaj register ako `sensor` (raw uint16):
```yaml
sensors:
  - name: "iterm_tepelko Stav prepínača raw"
    address: 2
    input_type: holding
    data_type: uint16
    scan_interval: 30
```

Krok 2 — v `configuration.yaml` (mimo modbus sekcie) pridaj template binary_sensors:
```yaml
template:
  - binary_sensor:
      - name: "SG Signál"
        state: "{{ (states('sensor.iterm_tepelko_stav_prepinaca_raw') | int(0)) | bitwise_and(1) > 0 }}"
        device_class: power
      - name: "EVU Signál"
        state: "{{ (states('sensor.iterm_tepelko_stav_prepinaca_raw') | int(0)) | bitwise_and(2) > 0 }}"
      - name: "Prietok vody"
        state: "{{ (states('sensor.iterm_tepelko_stav_prepinaca_raw') | int(0)) | bitwise_and(32) > 0 }}"
        device_class: moisture
```

---

## `switch` — Prepínač (čítanie + zápis)

Číta a zapisuje ON/OFF stav do **coil** alebo **holding** registra.

**Parametre:**
- Register type: `coil` (default) / `holding`
- `command_on` / `command_off` — hodnoty pre zápis (default 1/0)
- `state_on` / `state_off` — hodnoty pre čítanie
- `verify_address` — voliteľná adresa pre overenie stavu po zápise

**Príklad — coil:**
```yaml
switches:
  - name: "iterm_tepelko Vypínač"
    address: 100
    slave: 1
    write_type: coil
    scan_interval: 10
```

**Príklad — holding register:**
```yaml
switches:
  - name: "iterm_tepelko Vypínač"
    address: 8192
    slave: 1
    write_type: holding
    command_on: 1
    command_off: 0
    verify:
      address: 8192
      input_type: holding
    scan_interval: 10
```

> ⚠️ Switch zapisuje celú 16-bitovú hodnotu. Pre registre s viacerými bitmi (Control Flags)
> použi `modbus.write_register` service v automatizácii aby si nezmazal ostatné bity.

---

## `climate` — Termostat (čítanie + zápis teploty)

Čítanie aktuálnej teploty + zápis cieľovej teploty + voliteľné HVAC režimy.
Ide o najbližší ekvivalent "number entity pre teploty" v HA Modbus.

**Parametre:**
- Adresa registra — čítanie aktuálnej teploty (current temp)
- `target_temp_register` — adresa pre zápis setpointu
- `min_temp`, `max_temp`, `temp_step`, `scale`, `precision`
- `hvac_mode_register` + `hvac_mode_values` — voliteľné mapovanie režimov
- `hvac_onoff_register` — voliteľná adresa pre on/off

**Príklad — nastavenie teploty TÚV:**
```yaml
climates:
  - name: "iterm_tepelko Teplota TÚV"
    address: 15
    slave: 1
    input_type: holding
    data_type: int16
    scale: 0.1
    precision: 1
    min_temp: 28
    max_temp: 60
    temp_step: 1
    temperature_unit: C
    target_temp_register: 8197
    scan_interval: 30
```

**Príklad — s HVAC režimami:**
```yaml
climates:
  - name: "iterm_tepelko Kúrenie"
    address: 18
    slave: 1
    input_type: holding
    data_type: int16
    scale: 0.1
    min_temp: 15
    max_temp: 50
    temp_step: 1
    temperature_unit: C
    target_temp_register: 8199
    hvac_mode_register:
      address: 8194
      write_registers: false
      values:
        state_heat: 1
        state_cool: 2
        state_off: 0
    hvac_onoff_register: 8192
    scan_interval: 30
```

---

# ESPHome entity typy

ESPHome YAML je generovaný pre ESPHome kompilátor, nie priamo pre HA.

## `sensor` — Senzor
Modbus register senzor s podporou ESPHome filtrov (moving_average, calibrate_linear...).

## `binary_sensor` — Binárny senzor
Na rozdiel od HA Modbus, ESPHome binary_sensor **podporuje bitmask priamo pre holding registre**.

## `number` — Číselná hodnota (slider, čítanie + zápis)
Slider v HA UI. Plne podporované len v ESPHome.

## `switch` — Prepínač
Rovnaké ako Modbus switch.

## `select` — Výberové pole (čítanie + zápis)
**Spustí samostatný dialog** kde zadáš options map + lambda pre čítanie/zápis.

## `text_sensor` — Textový senzor
**Spustí samostatný dialog** kde zadáš template.

## `integration_sensor` — Integračný senzor (kumulatívna hodnota)
Napr. kWh z W. **Spustí samostatný dialog** kde zadáš zdrojový senzor a časovú jednotku (`s`/`min`/`h`/`d`).

## `bitmask_sensor` — Bitmaskový senzor (ESPHome only)
Z jedného raw senzora vytvorí interný binárny senzor + text_sensor ("Zapnutý"/"Vypnutý").
**Spustí samostatný dialog** kde zadáš bitmask, ID text_senzora a texty pre true/false.

```yaml
# Príklad výstupu:
sensor:
  - platform: modbus_controller
    id: kompressor_raw
    address: 4
    bitmask: 0x01
    internal: true

text_sensor:
  - platform: template
    name: "Kompresor"
    lambda: |-
      if (id(kompressor_raw).state) return {"Zapnutý"};
      return {"Vypnutý"};
```

---

# Šablóny zariadení

Ukladajú sa v `/config/proto_config_templates/`. Formát:

```json
{
  "connection_type": "modbus_rtu",
  "name": "moje_zariadenie",
  "connection_params": {
    "port": "/dev/ttyUSB0",
    "baudrate": 9600,
    "parity": "N",
    "stop_bits": 1,
    "slave": 1
  },
  "registers": [
    {
      "register": 14,
      "name": "vstupna_teplota",
      "friendly_name": "Vstupná teplota",
      "register_type": "holding",
      "data_type": "int16",
      "entity_type": "sensor",
      "scale": 0.1,
      "precision": 1,
      "unit": "°C",
      "device_class": "temperature",
      "state_class": "measurement",
      "scan_interval": 10
    }
  ]
}
```

---

# OptionsFlow — Editácia zariadenia

**Settings → Devices & Services → ProtoConfig → Configure**

- **➕ Add register** — sensor / binary_sensor / switch / climate
- **📊 Add integration sensor** — ESPHome only
- **🔲 Add bitmask sensor** — ESPHome only
- **📝 Add text sensor** — ESPHome only
- **🔧 Edit connection parameters**
- **✏️ Rename device**
- **🗑️ Delete a register**
- **🔄 Regenerate & reload YAML**
- **💾 Save changes**

---

# Services

| Service | Parametre | Popis |
|---------|-----------|-------|
| `proto_config.reload` | `device_id` (voliteľné) | Regeneruje YAML pre jedno alebo všetky zariadenia |
| `proto_config.export` | `device_id`, `output_path` | Exportuje konfiguráciu do JSON |
| `proto_config.import` | `config_path` | Importuje konfiguráciu z JSON |

---

# Backlog

- **v0.3.0** — Wizard dialóg pre `climate` entitu (current/target temp reg, HVAC módy)
- **v0.3.0** — Wizard dialóg pre `switch` entitu (holding vs coil, command values, verify)
- **v0.4.0** — Automatické generovanie Template binary_sensors pre bitmaskové holding registre
- **v0.4.0** — `cover`, `fan`, `light` entity typy pre Modbus
- **budúcnosť** — Lovelace dashboard generátor, MQTT podpora
