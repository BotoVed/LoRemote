"""LoRemote Protocol — MessagePack encode/decode."""
from __future__ import annotations

import msgpack
import logging
from .const import (
    PKT_CONFIRM, PKT_STATUS, PKT_PUSH, PKT_CONFIG, PKT_CMD, PKT_PING,
    SEC_META, SEC_AREAS, SEC_DEVICES, SEC_MAPPING, SEC_USERS,
)

_LOGGER = logging.getLogger(__name__)


def _int(v, default=0):
    try:
        return int(v) if v is not None else default
    except (ValueError, TypeError):
        return default


def _float(v, default=None):
    try:
        return float(v) if v is not None else default
    except (ValueError, TypeError):
        return default


class Protocol:
    """Encode and decode LoRemote packets using MessagePack."""

    def encode(self, data: dict) -> bytes:
        """Encode dict to MessagePack bytes."""
        return msgpack.packb(data, use_bin_type=True)

    def decode(self, raw: bytes) -> dict:
        """Decode MessagePack bytes to dict."""
        return msgpack.unpackb(raw, raw=False)

    # ── Outgoing (HA → phone) ──────────────────────────────────────────────

    def make_confirm(self, short_id: str, state: dict) -> bytes:
        """tp:1 — confirm command executed."""
        return self.encode({"tp": PKT_CONFIRM, "id": short_id, **state})

    def make_status(self, short_id: str, state: dict) -> bytes:
        """tp:2 — response to status request."""
        return self.encode({"tp": PKT_STATUS, "id": short_id, **state})

    def make_push(self, short_id: str, state: dict) -> bytes:
        """tp:3 — push state change."""
        return self.encode({"tp": PKT_PUSH, "id": short_id, **state})

    def make_config_meta(self, meta: dict) -> bytes:
        """tp:4 sec:meta — config meta packet."""
        return self.encode({"tp": PKT_CONFIG, "s": SEC_META, **meta})

    def make_config_page(self, section: str, page: int, total: int, data: list) -> bytes:
        """tp:4 — paginated config packet."""
        return self.encode({
            "tp": PKT_CONFIG,
            "s": section,
            "pg": page,
            "pgt": total,
            "d": data,
        })

    def make_pong(self, ts: int, cfgh: str) -> bytes:
        """tp:6 — ping response with config hash."""
        return self.encode({"tp": PKT_PING, "ts": ts, "cfgh": cfgh})

    # ── State extraction (entity → compact dict) ─────────────────────────

    def extract_state(self, entity_id: str, state, device_type: str) -> dict:
        """Extract compact state dict from HA state object."""
        attrs = state.attributes if state else {}
        s = state.state if state else "unavailable"

        if device_type == "L":
            return {
                "s": 1 if s == "on" else 0,
                "bri": _int(attrs.get("brightness", 0) or 0),
                "ct": _int(attrs.get("color_temp", 4000) or 4000),
            }
        elif device_type in ("SW", "SI"):
            return {"s": 1 if s == "on" else 0}

        elif device_type == "C":
            return {
                "s": 0 if s in ("off", "unavailable") else 1,
                "th": _float(attrs.get("temperature")),
                "tc": _float(attrs.get("current_temperature")),
                "md": attrs.get("hvac_mode"),
                "fn": attrs.get("fan_mode"),
            }
        elif device_type == "WH":
            return {
                "s": 0 if s in ("off", "unavailable") else 1,
                "th": _float(attrs.get("target_temp_high") or attrs.get("temperature")),
                "tc": _float(attrs.get("current_temperature")),
                "md": attrs.get("operation_mode"),
            }
        elif device_type == "F":
            return {
                "s": 1 if s == "on" else 0,
                "sp": _int(attrs.get("percentage", 0) or 0),
            }
        elif device_type == "CV":
            return {
                "st": s,
                "pos": _int(attrs.get("current_position", 0) or 0),
            }
        elif device_type == "LK":
            return {"s": s}

        elif device_type == "BS":
            return {"s": 1 if s == "on" else 0}

        elif device_type == "S":
            try:
                v = _float(s, 0)
            except (ValueError, TypeError):
                v = s
            return {
                "v": v,
                "u": attrs.get("unit_of_measurement"),
            }
        elif device_type == "A":
            return {"st": s}

        elif device_type == "H":
            return {
                "s": 1 if s == "on" else 0,
                "th": _float(attrs.get("humidity")),
                "tc": _float(attrs.get("current_humidity")),
            }
        else:
            return {"s": s}
