# LoRemote — Agent Instructions

## Инфраструктура
- Proxmox: 192.168.1.37:8006 root/775654Pr!
- HAOS: 192.168.1.114:8123, SSH :222 root/775Ho
- T114: /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0, node !077ccb09

## Workflow
Код → проверить синтаксис ast.parse → коммит → манифест версию → тег → Release с ZIP → HACS

### Шаблон релиза (ОБЯЗАТЕЛЬНО с ZIP!):
```bash
cd /tmp && mkdir -p pkg/custom_components/loremote
cp -r /repo/custom_components/loremote/* pkg/custom_components/loremote/
cd pkg && zip -r /tmp/loremote.zip custom_components/ && cd ..
git tag vX.Y.Z && git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z" --notes "..." --target main /tmp/loremote.zip
```
БЕЗ ZIP в релизе HACS не установит интеграцию (hacs.json: "filename": "loremote.zip")

## Структура
custom_components/loremote/
init.py, manifest.json, const.py, config_flow.py
coordinator.py, device_registry.py, ha_bridge.py
meshtastic_client.py, protocol.py, packet_store.py
sensor.py, strings.json
loremote-card/
brand/
  icon.png   ← иконка для HA UI (копируется из корня репо при сборке ZIP)
hacs.json

## Критичные паттерны
- Реестры: `from homeassistant.helpers import area_registry as ar` (hass.helpers.* устарело)
- pubsub: `def _on_connected(self, interface, topic=None)` — topic со дефолтом!
- Сенсоры >255 символов → хранить в extra_state_attributes['data'], не native_value
- Реконнект: _wait_for_device() ждёт /dev/ до 60 сек
- OptionsFlow: читать из entry.options с fallback на entry.data

## Протокол (MessagePack, порт 256)
tp:1=CONFIRM tp:2=STATUS tp:3=PUSH tp:4=CONFIG tp:5=CMD tp:6=PING
Доставка: попытки 1-3 hop=0, попытки 4-6 hop=7, таймаут 90с

## Типы устройств
L SW C WH F CV LK BS S SI B A H
Хэш: MD5[:6], коллизия → MD5[:7]

## Известные баги → решения
- HACS хэш вместо версии → нет Release или ZIP не прикреплён
- IndentationError → всегда ast.parse перед коммитом
- SenderMissingReqdMsgDataError → topic=None в pubsub колбэках
- Сенсор unknown → JSON в attributes, не native_value

## Известные проблемы и решения
| Иконка в HACS не показывается | Баг HACS #5171 — HACS не поддерживает локальные иконки HA 2026.3+. Не исправить. |
| Иконка в HA UI (Settings→Integrations) | brand/icon.png должна лежать в custom_components/loremote/brand/icon.png — копируется при сборке ZIP |

## Статус v0.2.8 ✅
Config/Options Flow, EntitySelector по доменам, Users CRUD,
экспорт конфига, 9 сенсоров, PacketStore, реконнект, HACS

## TODO
- HTML-клиент (Web Bluetooth → T1000-E)
