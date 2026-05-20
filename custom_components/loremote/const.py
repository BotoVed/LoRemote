"""Constants for LoRemote integration."""

DOMAIN = "loremote"
CONF_SERIAL_PORT = "serial_port"
CONF_NODE_ID = "node_id"
CONF_CHANNEL_NAME = "channel_name"
CONF_CHANNEL_KEY = "channel_key"
CONF_UPDATE_INTERVAL = "upd"
CONF_PUSH_ENABLED = "psh"
CONF_SELECTED_ENTITIES = "selected_entities"
CONF_ENTITY_NAMES = "entity_names"

# Packet types
PKT_CONFIRM = 1       # HA → phone: command confirmed
PKT_STATUS = 2        # HA → phone: status response
PKT_PUSH = 3          # HA → phone: state push
PKT_CONFIG = 4        # HA → phone: config
PKT_CMD = 5           # phone → HA: command or request
PKT_PING = 6          # phone → HA: keepalive

# Config sections
SEC_META = "meta"
SEC_AREAS = "ar"
SEC_DEVICES = "dev"
SEC_MAPPING = "mpg"
SEC_USERS = "usr"

# Device types
TYPE_LIGHT = "L"
TYPE_SWITCH = "SW"
TYPE_CLIMATE = "C"
TYPE_WATER_HEATER = "WH"
TYPE_FAN = "F"
TYPE_COVER = "CV"
TYPE_LOCK = "LK"
TYPE_BINARY_SENSOR = "BS"
TYPE_SENSOR = "S"
TYPE_SIREN = "SI"
TYPE_BUTTON = "B"
TYPE_SCENE = "B"
TYPE_ALARM = "A"
TYPE_HUMIDIFIER = "H"

# Map HA domain → our type code
DOMAIN_TO_TYPE = {
    "light": TYPE_LIGHT,
    "switch": TYPE_SWITCH,
    "climate": TYPE_CLIMATE,
    "water_heater": TYPE_WATER_HEATER,
    "fan": TYPE_FAN,
    "cover": TYPE_COVER,
    "lock": TYPE_LOCK,
    "binary_sensor": TYPE_BINARY_SENSOR,
    "sensor": TYPE_SENSOR,
    "siren": TYPE_SIREN,
    "button": TYPE_BUTTON,
    "scene": TYPE_SCENE,
    "alarm_control_panel": TYPE_ALARM,
    "humidifier": TYPE_HUMIDIFIER,
}

# Supported domains for selection in UI
SUPPORTED_DOMAINS = list(DOMAIN_TO_TYPE.keys())

# Delivery
RETRY_INTERVAL_SEC = 90
MAX_ATTEMPTS = 6          # 3x hop=0, 3x hop=7
HOP_LIMIT_DIRECT = 0
HOP_LIMIT_MESH = 7
HOP_SWITCH_AT = 3         # switch to mesh after this many attempts

# Keepalive
DEFAULT_UPDATE_INTERVAL = 60   # seconds
PING_OFFLINE_THRESHOLD = 3     # missed pings before offline

# Hash
HASH_LENGTH = 6
HASH_LENGTH_FALLBACK = 7      # on collision

# Roles
ROLE_ADMIN = "adm"
ROLE_VIEW = "viw"

# Meshtastic port
MESHTASTIC_PORT_NUM = 256     # PortNum.PRIVATE_APP
