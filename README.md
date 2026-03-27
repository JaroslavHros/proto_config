# ProtoConfig v0.2 — Home Assistant Custom Integration

**ProtoConfig** je custom HA integrácia ktorá ti umožní nakonfigurovať ľubovoľné Modbus (TCP/RTU) alebo ESPHome zariadenie cez UI wizard v Home Assistant — bez ručného písania YAML.

---

## Obsah

1. [Inštalácia](#1-inštalácia)
2. [Prvé spustenie — pridanie zariadenia](#2-prvé-spustenie--pridanie-zariadenia)
3. [Typy pripojenia](#3-typy-pripojenia)
4. [Pridávanie registrov](#4-pridávanie-registrov)
5. [Entity typy — Modbus](#5-entity-typy--modbus)
6. [Entity typy — ESPHome](#6-entity-typy--esphome)
7. [Úprava zariadenia (OptionsFlow)](#7-úprava-zariadenia-optionsflow)
8. [Šablóny zariadení](#8-šablóny-zariadení)
9. [Services](#9-services)
10. [Vygenerované súbory](#10-vygenerované-súbory)
11. [Riešenie problémov](#11-riešenie-problémov)

---

## 1. Inštalácia

### Požiadavky

- Home Assistant OS, Supervised, alebo Container
- Python 3.11+
- `pyyaml>=6.0` (automaticky nainštalované)

### Krok 1 — Skopíruj súbory

Skopíruj priečinok `proto_config` do `custom_components` v tvojom HA config priečinku:

```
/config/
  custom_components/
    proto_config/
      __init__.py
      config_flow.py
      const.py
      manifest.json
      services.py
      services.yaml
      storage.py
      strings.json
      template_loader.py
      generators/
        __init__.py
        modbus_generator.py
        esphome_generator.py
      translations/
        en.json
```

### Krok 2 — Reštartuj Home Assistant

**Settings → System → Restart**

### Krok 3 — Pridaj integráciu

**Settings → Devices & Services → Add Integration → hľadaj "ProtoConfig"**

---

## 2. Prvé spustenie — pridanie zariadenia

Po kliknutí na **Add Integration** sa spustí wizard:

### Krok 1 — Základné info

| Pole | Popis |
|------|-------|
| **Názov zariadenia** | Ľubovoľný názov, napr. `Iterm TČ`. Z neho sa automaticky vytvorí ID (`iterm_tc`) a názov YAML súboru. Diakritika sa transliteruje (Č→C, Š→S...). |
| **Typ pripojenia** | `modbus_tcp` / `modbus_rtu` / `esphome` |
| **Interval čítania** | Default 30 sekúnd — globálny, dá sa prebiť na úrovni registra |
| **Šablóna** | Voliteľné — načíta predpripravenú sadu registrov z JSON šablóny |

### Krok 2 — Parametre pripojenia

Podľa zvoleného typu pripojenia:

**Modbus TCP:**
- IP adresa zariadenia
- Port (default `502`)
- Slave ID (default `1`)

**Modbus RTU:**
- Sériový port (napr. `/dev/ttyUSB0`)
- Baud rate (napr. `9600`)
- Slave ID
- Parita (`N` / `E` / `O`)
- Stop bity (`1` / `2`)

**ESPHome:**
- Platforma (`ESP32` / `ESP8266`)
- Typ dosky (napr. `esp32dev`)
- TX/RX piny
- Baud rate, Slave ID, Parita, Stop bity

### Krok 3 — Pridávanie registrov

Opakovane pridávaš registre (senzory, prepínače...). Každý register = jedna HA entita.
Po pridaní všetkých registrov zaškrtni **"Dokončiť pridávanie registrov"**.

### Krok 4 — Generovanie

Po dokončení wizardu ProtoConfig automaticky:
1. Uloží konfiguráciu do HA storage
2. Vygeneruje YAML súbor do správneho priečinka
3. Reloadne Modbus/ESPHome integráciu

---

## 3. Typy pripojenia

### Modbus TCP

Zariadenie komunikuje cez Ethernet/WiFi. HA sa pripája ako Modbus master.

Výstupný súbor: `/config/modbus/nazov_zariadenia.yaml`

Tento súbor musíš includovať v `configuration.yaml`:
```yaml
modbus: !include_dir_merge_list modbus/
```

### Modbus RTU

Zariadenie je pripojené cez RS-485 (USB adaptér alebo sériový port).

Výstupný súbor: `/config/modbus/nazov_zariadenia.yaml`

Rovnaký include ako TCP.

### ESPHome

ESP32/ESP8266 s Modbus RTU slave zariadením. ESP funguje ako most — číta Modbus a posiela dáta do HA cez ESPHome API.

Výstupný súbor: `/config/esphome/nazov_zariadenia.yaml`

Tento YAML musíš skompilovať a nahrať do ESP cez ESPHome addon v HA.

---

## 4. Pridávanie registrov

Každý register má tieto spoločné polia:

| Pole | Popis |
|------|-------|
| **Interný názov (ID)** | Technický identifikátor bez diakritiky, napr. `vstupna_teplota`. Použije sa v `unique_id`. |
| **Zobrazovaný názov** | Čo sa zobrazí v HA UI, napr. `Vstupná teplota vody` |
| **Formát adresy** | `Decimal` alebo `Hexadecimal` — len pre zadávanie, v YAML sa vždy uloží ako hex (`0x000E`) |
| **Adresa registra** | Adresa registra podľa dokumentácie zariadenia |
| **Typ registra** | `holding` / `input` / `coil` / `discrete_input` |
| **Dátový typ** | `int16` / `uint16` / `int32` / `uint32` / `float32` / `int64` / `uint64` |
| **Typ entity** | Čo sa vytvorí v HA — závisí od typu pripojenia |
| **Koeficient** | Scale faktor, napr. `0.1` pre registre kde hodnota `253` = `25.3°C` |
| **Offset** | Pridá sa po scale, napr. `-273.15` pre Kelvin→Celsius |
| **Jednotka** | napr. `°C`, `%`, `W`, `kWh`, `bar` |
| **Device class** | napr. `temperature`, `power`, `energy` — ovplyvní ikonu a jednotky v HA |
| **State class** | `measurement` / `total` / `total_increasing` |

**Modbus-specific:**
- **Desatinné miesta (precision)** — počet desatín vo výsledku
- **Interval čítania** — prepíše globálny scan_interval pre tento register

**ESPHome-specific:**
- **Presnosť desatín** — `accuracy_decimals`
- **Ikona** — `mdi:thermometer` a pod.
- **Bitmask** — pre binary_sensor, napr. `0x0001`
- **Custom filters** — YAML list ESPHome filtrov (multiply, offset, calibrate_linear...)
- **Interný sensor** — ak zaškrtnuté, sensor sa nezobrazí v HA (použiteľné pre medzivýpočty)

---

## 5. Entity typy — Modbus

> Platí pre `modbus_tcp` a `modbus_rtu` pripojenie.

### `sensor` — Senzor (len čítanie)

Číta hodnotu z `holding` alebo `input` registra. Zobrazuje číselnú hodnotu v HA.

```yaml
sensors:
  - name: "Iterm TC Vstupná teplota vody"
    unique_id: iterm_tc_vstupna_teplota
    address: 0x000E
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

### `binary_sensor` — Binárny senzor (len čítanie)

Číta ON/OFF stav z `coil` alebo `discrete_input` registra.

> ⚠️ **HA Modbus `binary_sensor` nepodporuje bitmask ani holding registre.**
> Pre bitmaskové status registre (napr. register kde bit0=SG signál, bit1=EVU...) použi `sensor` (raw uint16) a v `configuration.yaml` si pridaj Template binary_sensors.

**Workaround pre bitmaskové holding registre:**

Krok 1 — v ProtoConfig nastav register ako `sensor`:
```yaml
sensors:
  - name: "Iterm TC Stav prepínača raw"
    address: 0x0002
    slave: 1
    input_type: holding
    data_type: uint16
    scan_interval: 30
```

Krok 2 — v `configuration.yaml` pridaj template binary_sensors:
```yaml
template:
  - binary_sensor:
      - name: "SG Signál"
        state: "{{ (states('sensor.iterm_tc_stav_prepinaca_raw') | int(0)) | bitwise_and(1) > 0 }}"
        device_class: power
      - name: "EVU Signál"
        state: "{{ (states('sensor.iterm_tc_stav_prepinaca_raw') | int(0)) | bitwise_and(2) > 0 }}"
      - name: "Prietok vody"
        state: "{{ (states('sensor.iterm_tc_stav_prepinaca_raw') | int(0)) | bitwise_and(32) > 0 }}"
        device_class: moisture
```

---

### `switch` — Prepínač (čítanie + zápis)

Číta a zapisuje ON/OFF stav do `coil` alebo `holding` registra. Zobrazí sa ako toggle v HA.

> ⚠️ Switch zapisuje celú 16-bitovú hodnotu. Pre registre kde sú bity s rôznymi funkciami (Control Flags) použi `modbus.write_register` service v automatizácii aby si nezmazal ostatné bity.

---

### `climate` — Termostat (čítanie + zápis teploty)

Čítanie aktuálnej teploty + zápis cieľovej teploty. Zobrazí sa ako termostat karta v HA.
Najblišší ekvivalent "number entity pre teploty" v HA Modbus.

Vyžaduje:
- Adresu registra pre čítanie aktuálnej teploty
- `target_temp_register` — adresu pre zápis setpointu
- `min_temp` a `max_temp`

Voliteľne:
- `hvac_mode_register` + hodnoty pre jednotlivé režimy (heat/cool/auto/off)
- `hvac_onoff_register` — oddelený register pre on/off

---

## 6. Entity typy — ESPHome

> Platí pre `esphome` pripojenie. YAML sa generuje pre ESPHome kompilátor.

### `sensor` — Senzor

Číta hodnotu z Modbus registra. Podporuje ESPHome filtre.

Pole **"Interný sensor"** — ak zaškrtnuteé, sensor sa nezobrazí v HA (hodí sa napr. pre zdrojový sensor k `integration_sensor`).

```yaml
sensor:
  - platform: modbus_controller
    name: "Vstupná teplota"
    id: vstupna_teplota
    address: 0x000E
    register_type: holding
    value_type: S_WORD
    unit_of_measurement: "°C"
    filters:
      - multiply: 0.1
```

---

### `binary_sensor` — Binárny senzor

Na rozdiel od HA Modbus, ESPHome `binary_sensor` **podporuje `bitmask` priamo pre holding registre**.

```yaml
binary_sensor:
  - platform: modbus_controller
    name: "SG Signál"
    address: 0x0002
    register_type: holding
    bitmask: 0x0001
```

---

### `number` — Číselná hodnota (slider, čítanie + zápis)

Zobrazí sa ako slider v HA UI. Umožňuje nastavovať hodnoty registrov.

---

### `switch` — Prepínač

Čítanie + zápis ON/OFF cez coil register.

---

### `select` — Výberové pole

**Spustí samostatný dialog** kde zadáš:
- Options map: JSON formát, napr. `{"TUV": 0, "Kurenie": 1, "Chladenie": 2}`
- Lambda pre čítanie (C++ kód)
- Lambda pre zápis (C++ kód)

---

### `text_sensor` — Textový senzor

Zobrazuje textovú hodnotu. **Spustí samostatný dialog** kde zadáš:
- Lambda (C++ kód ktorý vracia `std::string`)
- Interval aktualizácie

---

### `integration_sensor` — Integračný senzor

Vypočítava kumulatívnu hodnotu z iného senzora (napr. kWh z W, hodiny behu z ON/OFF).

**Spustí samostatný dialog** kde zadáš:
- ID zdrojového senzora (musí existovať v ESPHome YAML)
- Časovú jednotku: `s` / `min` / `h` / `d`

```yaml
sensor:
  - platform: integration
    name: "Spotreba energie"
    sensor: vykon_kompresora
    time_unit: h
    unit_of_measurement: "kWh"
```

---

### `bitmask_sensor` — Bitmaskový senzor

Z jedného raw senzora vytvorí interný binárny senzor + textový senzor (napr. "Zapnutý"/"Vypnutý").

**Spustí samostatný dialog** kde zadáš:
- Adresu a typ registra
- Bitmask (napr. `0x0001` pre bit0)
- ID a názov výstupného text senzora
- Text pre stav TRUE a FALSE

```yaml
# Výsledný YAML:
sensor:
  - platform: modbus_controller
    id: kompressor_raw
    address: 0x0004
    bitmask: 0x0001
    internal: true
    on_value:
      then:
        - lambda: |-
            if (x) id(kompressor_stav).publish_state("Zapnutý");
            else id(kompressor_stav).publish_state("Vypnutý");

text_sensor:
  - platform: template
    name: "Kompresor"
    id: kompressor_stav
```

---

## 7. Úprava zariadenia (OptionsFlow)

**Settings → Devices & Services → ProtoConfig → klikni na zariadenie → Configure**

Dostupné akcie:

| Akcia | Popis |
|-------|-------|
| **➕ Pridať register** | Pridá sensor / binary_sensor / switch / climate (Modbus) alebo všetky typy (ESPHome) |
| **📊 Pridať Integration Sensor** | ESPHome kumulatívny senzor (spustí dialog) |
| **🔲 Pridať Bitmask Sensor** | ESPHome bitmask senzor (spustí dialog) |
| **📝 Pridať Text Sensor** | ESPHome template text senzor (spustí dialog) |
| **🔧 Upraviť parametre pripojenia** | Zmeň IP, port, baudrate, slave ID... |
| **✏️ Premenovať zariadenie** | Premenuje zariadenie (aktualizuje aj YAML) |
| **🗑️ Vymazať register** | Vyberie register zo zoznamu a vymaže ho |
| **🔄 Regenerovať a reloadnúť** | Uloží zmeny, vygeneruje YAML, reloadne integráciu |
| **💾 Uložiť bez regenerácie** | Uloží zmeny bez generovania YAML |

### Dôležité

Po každej zmene musíš kliknúť na **Regenerovať a reloadnúť** aby sa zmeny prejavili v HA.
Bez toho sa YAML súbor neaktualizuje.

---

## 8. Šablóny zariadení

Šablóna je JSON súbor s predpripravenou sadou registrov pre konkrétny typ zariadenia.

### Kde sa ukladajú

```
/config/proto_config_templates/
  moja_sablona.json
  iterm_tepelko.json
```

### Formát šablóny

```json
{
  "connection_type": "modbus_rtu",
  "name": "Moje Zariadenie",
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
      "friendly_name": "Vstupná teplota vody",
      "register_type": "holding",
      "data_type": "int16",
      "entity_type": "sensor",
      "scale": 0.1,
      "precision": 1,
      "unit": "°C",
      "device_class": "temperature",
      "state_class": "measurement",
      "scan_interval": 10
    },
    {
      "register": 8205,
      "name": "teplota_tuv_setpoint",
      "friendly_name": "Teplota TÚV setpoint",
      "register_type": "holding",
      "data_type": "int16",
      "entity_type": "climate",
      "scale": 0.1,
      "min_temp": 28,
      "max_temp": 60,
      "temp_step": 1,
      "target_temp_register": 8205
    }
  ]
}
```

### Export existujúceho zariadenia ako šablóna

Použi service `proto_config.export` (pozri nižšie) — vygeneruje JSON ktorý môžeš použiť ako šablónu.

---

## 9. Services

Dostupné cez **Developer Tools → Actions** alebo v automatizáciách.

### `proto_config.reload`

Regeneruje YAML a reloadne integráciu.

```yaml
action: proto_config.reload
data:
  device_id: "iterm_tc"   # voliteľné — bez toho reloadne všetky zariadenia
```

### `proto_config.export`

Exportuje konfiguráciu zariadenia do JSON súboru (použiteľný ako šablóna).

```yaml
action: proto_config.export
data:
  device_id: "iterm_tc"
  output_path: "/config/proto_config_templates/iterm_tc_export.json"  # voliteľné
```

### `proto_config.import`

Importuje konfiguráciu zo JSON súboru a vytvorí nové zariadenie.

```yaml
action: proto_config.import
data:
  config_path: "/config/proto_config_templates/iterm_tc_export.json"
```

---

## 10. Vygenerované súbory

### Modbus YAML

Súbor: `/config/modbus/<nazov_zariadenia>.yaml`

Musí byť includovaný v `configuration.yaml`:
```yaml
modbus: !include_dir_merge_list modbus/
```

Príklad vygenerovaného súboru:
```yaml
# Auto-generated by ProtoConfig v0.2
# Device: iterm_tc
# DO NOT EDIT MANUALLY - Use ProtoConfig UI

- name: iterm_tc
  type: serial
  port: /dev/ttyUSB0
  baudrate: 9600
  bytesize: 8
  method: rtu
  parity: N
  stopbits: 1

  sensors:
    - name: "Iterm TC Vstupná teplota vody"
      unique_id: iterm_tc_vstupna_teplota
      address: 0x000E
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

### ESPHome YAML

Súbor: `/config/esphome/<nazov_zariadenia>.yaml`

Tento súbor skompiluj a nahraj do ESP cez **ESPHome addon → Open Web UI → nazov_zariadenia → Install**.

---

## 11. Riešenie problémov

### Integrácia sa nezobrazí po inštalácii

1. Skontroluj či je priečinok správne pomenovaný: `custom_components/proto_config/`
2. Skontroluj `manifest.json` — musí existovať
3. Reštartuj HA a skontroluj logy: **Settings → System → Logs**

### YAML súbor sa nevygeneroval

1. Skontroluj či existujú priečinky `/config/modbus/` resp. `/config/esphome/`
2. Ak nie, vytvor ich ručne alebo klikni na **Regenerovať a reloadnúť** — priečinky sa vytvoria automaticky
3. Skontroluj logy na chybu pri generovaní

### Modbus entity sa nenačítajú

1. Skontroluj `configuration.yaml` — musí obsahovať `modbus: !include_dir_merge_list modbus/`
2. Skontroluj vygenerovaný YAML — musí byť valídny (otvor ho a skopíruj do YAML validátora)
3. Skontroluj logy HA na Modbus chyby

### Hodnoty senzorov sú nesprávne

Skontroluj:
- **Adresu registra** — niektoré zariadenia používajú offset (napr. adresa `1` v dokumentácii = `0` alebo `40001` závisí od zariadenia)
- **Data type** — `int16` vs `uint16` (záporné hodnoty)
- **Scale** — napr. `0.1` pre hodnoty v desatinách

### Zariadenie s diakritikou v názve

ProtoConfig automaticky transliteruje diakritiku v ID a file_id:
- `Iterm TČ` → ID: `iterm_tc`, súbor: `iterm_tc.yaml`
- Friendly name zostáva pôvodný: `"Iterm TČ Vstupná teplota"`

---

## Architektúra (pre vývojárov)

```
config_flow.py          Wizard pre pridanie nového zariadenia (ConfigFlow)
                        + úprava existujúceho (OptionsFlow)
__init__.py             Hlavný modul — setup, YAML generovanie, reload
storage.py              Sync kópia konfigurácií zariadení (pre services)
services.py             HA services: reload, export, import
template_loader.py      Načítavanie JSON šablón z /config/proto_config_templates/
generators/
  modbus_generator.py   Generuje Modbus YAML (sensor, binary_sensor, switch, climate)
  esphome_generator.py  Generuje ESPHome YAML (všetky entity typy)
const.py                Konštanty, zoznamy entity typov, data typov
strings.json            Texty pre UI wizard (slovenčina)
translations/en.json    Texty pre UI wizard (angličtina)
```

### Tok dát

```
Wizard (config_flow) → entry.data/options → async_setup_entry → generátor → YAML súbor
                                                              → storage.save() → services
```

### Pridanie nového zariadenia — čo sa stane

1. Wizard zbiera dáta → uloží do `entry.data` s `needs_generate=True`
2. `async_setup_entry` detekuje `needs_generate=True`
3. Vyčistí flag, zavolá príslušný generátor
4. Generátor zapíše YAML súbor
5. HA reloadne Modbus/ESPHome integráciu