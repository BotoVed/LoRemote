# LoRemote Android — Agent Instructions

## Репозиторий
https://github.com/BotoVed/LoRemoteApp (branch: main)
Часть экосистемы [LoRemote](https://github.com/BotoVed/LoRemote)

## Окружение разработки

- **Машина**: Ubuntu 24, user: boss
- **Java**: openjdk-21 (`/usr/lib/jvm/java-21-openjdk-amd64`)
- **Android SDK**: `~/android-sdk` (SDK 34, build-tools 34.0.0)
- **Gradle**: `/tmp/gradle-8.6/bin/gradle` — НЕ системный (системный 4.4 — слишком старый)
- **ADB**: `~/android-sdk/platform-tools/adb`
- **Проект**: `~/loremote-android`

## Workflow

```
читать InstructionForAgent.md
→ писать/менять код
→ собрать: export ANDROID_HOME=~/android-sdk && /tmp/gradle-8.6/bin/gradle assembleDebug --no-daemon
→ установить: ~/android-sdk/platform-tools/adb install -r app/build/outputs/apk/debug/app-debug.apk
→ логи: ~/android-sdk/platform-tools/adb logcat -s "BleService" "BleManager" "MainActivity" "BleScanner"
→ коммит + push
→ обновить InstructionForAgent.md
```

### Шаблон коммита
```bash
git add -A
git commit -m "vX.Y.Z — описание"
git push origin main
```

## Структура проекта

```
app/src/main/java/com/loremote/app/
  ble/
    BleService.kt      — Foreground Service, держит BLE живым в фоне
    BleManager.kt      — Meshtastic BLE API (ToRadio/FromRadio/FromNum)
    BleScanner.kt      — сканирование BLE устройств
  protocol/
    Protocol.kt        — MessagePack encode/decode + wrapInToRadio()
    Packet.kt          — OutPacket, PacketType, GATEWAY_NODE_NUM
    DeliveryQueue.kt   — гарантия доставки (6 попыток, coroutines)
  ui/
    MainActivity.kt    — UI: bindService + BroadcastReceiver
  App.kt
app/src/main/proto/
  mesh.proto           — FromRadio, ToRadio, MeshPacket, Data (protobuf lite)
```

## Железо

- **T1000-E** `AleX_c891` MAC: `EF:A6:95:F2:C8:91` node `!95f2c891` — BLE клиент
- **T114** node `!077ccb09` = `125747977` decimal — шлюз на стороне HA
- **HAOS**: `192.168.1.114:8123`, SSH `:222` root/775Ho
- **T114 serial**: `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`
- **PIN паринга T1000-E**: `123456` (Meshtastic FIXED_PIN)

## Meshtastic BLE API

T1000-E использует Meshtastic BLE API, **не** Nordic UART Service:

```
Service:   6ba1b218-15a8-461f-9fa8-5dcae273eafd
ToRadio:   f75c76d2-129e-4dad-a1dd-7866124401e7  (write)
FromRadio: 2c55e69e-4993-11ed-b878-0242ac120002  (read)
FromNum:   ed9da18c-a800-4f66-a670-aa7547e34453  (notify)
```

### Handshake
```
1. connect() + requestMTU(512) → реальный MTU=247
2. enableNotifications(fromNum)
3. write(toRadio, [0x18, 0x00])   ← startConfig (want_config_id=0)
4. poll fromRadio пока не пустой
5. получить CONFIG_COMPLETE_ID (field 6) → BleState.Ready
6. при notify fromNum → читать fromRadio в цикле
```

### Отправка пакета (КЛЮЧЕВОЕ)
```
to = 0xFFFFFFFF  ← broadcast (не direct message!)
channel = 0      ← PRIMARY (LongFast, key=AQ==)
portnum = 256    ← PRIVATE_APP
```
Direct message (to=node_num) не работает — Meshtastic 2.x использует PKC шифрование для DM, у нас нет ключей. Только broadcast.

### Protobuf (mesh.proto)
```protobuf
message Data      { uint32 portnum=1; bytes payload=2; }
message MeshPacket { fixed32 from=1; fixed32 to=2; Data decoded=3; fixed32 id=9; ... }
message FromRadio  { oneof { MeshPacket packet=2; uint32 config_complete_id=6; ... } }
message ToRadio    { oneof { MeshPacket packet=1; uint32 want_config_id=3; } }
```
**fixed32** для from/to/id — не uint32! Иначе portnum=0 при парсинге.

## Наш протокол (поверх Meshtastic)

Порт: `PRIVATE_APP = 256`, сериализация: **MessagePack**

```
tp:1 CONFIRM  — HA→телефон, команда выполнена
tp:2 STATUS   — HA→телефон, состояние по запросу
tp:3 PUSH     — HA→телефон, изменение состояния
tp:4 CONFIG   — HA→телефон, конфиг (пагинация pg/pgt)
tp:5 CMD      — телефон→HA, команда
tp:6 PING     — телефон→HA / PONG с cfgh в ответ
```

### DeliveryQueue
- Попытки 1-3: `hl=0` (прямая), 4-6: `hl=7` (через mesh)
- Таймаут: 90 сек, подтверждение по tp:1 CONFIRM

## Уточнения от мобильного приложения (финальный протокол)

- Приложение шлёт broadcast (to=0xFFFFFFFF), не direct message
- Плагин принимает пакеты от любого узла
- Поле hl (hop limit) передаётся внутри пакета
- CONFIRM (tp:1) всегда содержит РЕАЛЬНОЕ состояние устройства из HA
  (не эхо команды) — приложение применяет его напрямую
- req="all" (tp:5) → плагин отвечает серией tp:2 STATUS
- Числовые поля могут приходить как Int или Long — оба типа валидны

## Foreground Service архитектура

```
BleService (LifecycleService — всегда жив, START_STICKY)
    ├── LoRemoteBleManager
    ├── BleScanner
    ├── pingLoop — каждые 60 сек если Ready
    ├── updateNotification() — статус в шторке
    └── sendBroadcast(ACTION_PACKET) → MainActivity

MainActivity
    ├── startForegroundService() + bindService()
    ├── BroadcastReceiver(ACTION_PACKET) → handlePacket()
    └── onStop(): unbind но НЕ stopService
```

### Permissions (AndroidManifest.xml)
```xml
FOREGROUND_SERVICE
FOREGROUND_SERVICE_CONNECTED_DEVICE
POST_NOTIFICATIONS
```
```xml
<service android:name=".ble.BleService"
         android:foregroundServiceType="connectedDevice"
         android:exported="false"/>
```

## Зависимости (app/build.gradle.kts)

```
AGP: 8.4.0, Kotlin: 1.9.22, JVM target: 21, Gradle: 8.6
nordic ble: 2.7.4 + ble-ktx:2.7.4
msgpack-core: 0.9.8
protobuf-kotlin-lite: 3.25.1
coroutines-android: 1.7.3
lifecycle-service: 2.7.0
lifecycle-runtime-ktx: 2.7.0
appcompat: 1.6.1, material: 1.11.0
```

## Критичные паттерны

- `LifecycleService` для BleService (не просто Service) — нужны coroutines
- `setGattCallbacks(this)` перед `connect()`
- `BleManagerCallbacks` интерфейс — не переопределять методы напрямую
- `BleState.Ready` устанавливать при `CONFIG_COMPLETE_ID`, не при пустом буфере
- Broadcast пакеты (не DM) — `to=0xFFFFFFFF, channel=0`
- `SharedPreferences("loremote")` — хранить `last_device_mac`, `last_device_name`
- `source ~/.bashrc` перед командами если нужен nvm

## Известные проблемы → решения

| Проблема | Решение |
|---------|---------|
| portnum=0 при парсинге | fixed32 для from/to/id в MeshPacket, не uint32 |
| PING не уходит после Ready | Слать в state.collect{ Ready }, не в onDeviceReady |
| Direct message не доходит | Только broadcast to=0xFFFFFFFF |
| BLE рвётся в фоне | Foreground Service с START_STICKY |
| Gradle не найден | `/tmp/gradle-8.6/bin/gradle`, не системный |
| Nordic API | v2.7.4 требует BleManagerCallbacks интерфейс |
| T1000-E не виден в скане | Закрыть Meshtastic app — BLE занят |

## Статус v0.2.3 ✅

- [x] BLE сканирование + фильтрация Meshtastic устройств
- [x] Автоподключение к последнему устройству (SharedPreferences)
- [x] Meshtastic handshake (config_complete_id → Ready)
- [x] Protobuf парсинг FromRadio (fixed32, все типы handshake)
- [x] Broadcast отправка portnum=256
- [x] PING доходит до T114, плагин получает
- [x] MessagePack encode/decode
- [x] DeliveryQueue (6 попыток)

## TODO (следующие шаги)

1. **Foreground Service** — BleService.kt, переделать MainActivity на bindService ← **СЛЕДУЮЩИЙ**
2. **PONG от T114** — проверить что плагин отвечает на PING
3. **Полный UI** — зоны, карточки устройств (на основе LORA_CONFIG)
4. **Авторизация** — SHA-256 пароль, несколько пользователей
5. **Алармы** — уведомления при tp:3 с BS датчиками
