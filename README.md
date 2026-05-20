# LoRemote

Home Assistant custom integration for remote control via LoRa/Meshtastic mesh network.

Works completely **without internet** — uses LoRa radio for communication.

## Features
- Control lights, switches, climate, covers, locks and more
- Real-time sensor updates via LoRa push
- Works with Meshtastic devices (T114, T1000-E)
- Compact MessagePack protocol optimized for LoRa bandwidth
- Zone-based UI with device grouping

## Requirements
- Heltec Mesh Node T114 connected via USB
- Home Assistant OS 2024.1+
- HACS

## Installation
1. Add this repository to HACS as custom integration
2. Install LoRemote via HACS
3. Restart Home Assistant
4. Go to Settings → Integrations → Add → LoRemote
5. Select serial port and channel settings
6. Choose devices to expose via LoRa

## Supported device types
- Light (on/off + brightness + color temperature)
- Switch
- Climate (target temp + mode + fan)
- Water heater
- Fan
- Cover (open/close/position)
- Lock
- Binary sensor
- Sensor
- Siren
- Button / Scene
- Alarm control panel
- Humidifier
