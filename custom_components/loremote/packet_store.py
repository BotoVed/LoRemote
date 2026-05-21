"""Packet store — keeps packet log, connection history, sessions."""
from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Literal


@dataclass
class PacketEntry:
    ts: int                          # unix timestamp
    dir: Literal["rx", "tx"]        # входящий / исходящий
    node: str                        # !ed4b36ba
    ptype: str                       # PING, CMD, PUSH...
    size: int                        # байт
    status: Literal["ok","fail","wait"]  # статус доставки
    hop: int                         # hop_limit использованный
    rssi: int | None                 # только для rx
    snr: float | None                # только для rx
    attempts: int                    # количество попыток
    payload_json: str                # декодированный JSON
    payload_hex: str                 # сырые байты hex


@dataclass
class ConnEvent:
    ts: int
    event: Literal["online", "offline"]
    duration_sec: int | None
    reason: str | None


@dataclass
class SessionEntry:
    ts: int
    user_name: str
    node: str


PACKET_TYPE_NAMES = {
    1: "CONFIRM",
    2: "STATUS",
    3: "PUSH",
    4: "CONFIG",
    5: "CMD",
    6: "PING/PONG",
}


class PacketStore:
    """Stores packet log, connection history and sessions."""

    MAX_PACKETS = 20
    MAX_CONN_EVENTS = 100
    MAX_SESSIONS = 20

    def __init__(self):
        self._packets: deque[PacketEntry] = deque(maxlen=self.MAX_PACKETS)
        self._conn_events: deque[ConnEvent] = deque(maxlen=self.MAX_CONN_EVENTS)
        self._sessions: deque[SessionEntry] = deque(maxlen=self.MAX_SESSIONS)
        self._last_online_ts: int | None = None
        self._is_online: bool = False

    def add_rx(self, node: str, payload: bytes, decoded: dict,
               rssi: int | None, snr: float | None, hop: int) -> PacketEntry:
        tp = decoded.get("tp", 0)
        entry = PacketEntry(
            ts=int(time.time()),
            dir="rx",
            node=node,
            ptype=PACKET_TYPE_NAMES.get(tp, f"TYPE_{tp}"),
            size=len(payload),
            status="ok",
            hop=hop,
            rssi=rssi,
            snr=snr,
            attempts=1,
            payload_json=json.dumps(decoded, ensure_ascii=False),
            payload_hex=payload.hex(" "),
        )
        self._packets.appendleft(entry)
        return entry

    def add_tx(self, node: str, payload: bytes, decoded: dict,
               hop: int, attempt: int = 1) -> PacketEntry:
        tp = decoded.get("tp", 0)
        entry = PacketEntry(
            ts=int(time.time()),
            dir="tx",
            node=node,
            ptype=PACKET_TYPE_NAMES.get(tp, f"TYPE_{tp}"),
            size=len(payload),
            status="wait",
            hop=hop,
            rssi=None,
            snr=None,
            attempts=attempt,
            payload_json=json.dumps(decoded, ensure_ascii=False),
            payload_hex=payload.hex(" "),
        )
        self._packets.appendleft(entry)
        return entry

    def confirm_tx(self, node: str, ptype: str):
        """Mark latest matching tx packet as ok."""
        for p in self._packets:
            if p.dir == "tx" and p.node == node and p.ptype == ptype and p.status == "wait":
                p.status = "ok"
                break

    def fail_tx(self, node: str, ptype: str, attempts: int):
        """Mark tx packet as failed."""
        for p in self._packets:
            if p.dir == "tx" and p.node == node and p.ptype == ptype and p.status == "wait":
                p.status = "fail"
                p.attempts = attempts
                break

    def on_connected(self):
        # Не добавлять дубль если уже online
        if self._is_online:
            return
        self._is_online = True
        self._last_online_ts = int(time.time())
        self._conn_events.appendleft(ConnEvent(
            ts=int(time.time()),
            event="online",
            duration_sec=None,
            reason=None,
        ))

    def on_disconnected(self, reason: str = None):
        # Не добавлять дубль если уже offline
        if not self._is_online and self._conn_events:
            # Обновить reason последнего события если он None
            last = self._conn_events[0]
            if last.event == "offline" and last.reason is None and reason:
                last.reason = reason
            return
        duration = None
        if self._last_online_ts:
            duration = int(time.time()) - self._last_online_ts
        self._is_online = False
        self._conn_events.appendleft(ConnEvent(
            ts=int(time.time()),
            event="offline",
            duration_sec=duration,
            reason=reason,
        ))

    def add_session(self, user_name: str, node: str):
        self._sessions.appendleft(SessionEntry(
            ts=int(time.time()),
            user_name=user_name,
            node=node,
        ))

    def uptime_24h(self) -> int:
        """Calculate uptime % for last 24h."""
        now = int(time.time())
        window = 24 * 3600
        start = now - window
        online_sec = 0
        events = list(self._conn_events)
        for i, ev in enumerate(events):
            if ev.event == "online":
                on_ts = max(ev.ts, start)
                off_ts = now
                if i > 0:
                    prev = events[i - 1]
                    if prev.event == "offline":
                        off_ts = min(prev.ts, now)
                online_sec += max(0, off_ts - on_ts)
        if not events:
            return 100 if self._is_online else 0
        return min(100, int(online_sec * 100 / window))

    def to_sensor_values(self) -> dict:
        def trim_packet(p: dict) -> dict:
            result = dict(p)
            if result.get("payload_hex"):
                result["payload_hex"] = result["payload_hex"][:32] + "..."
            return result

        packets = [trim_packet(asdict(p)) for p in self._packets]
        conn = [asdict(e) for e in self._conn_events]
        sessions = [asdict(s) for s in self._sessions]
        last_rx = next((p for p in packets if p["dir"] == "rx"), None)
        last_tx = next((p for p in packets if p["dir"] == "tx"), None)
        return {
            "packet_log": json.dumps(packets),
            "conn_history": json.dumps(conn),
            "sessions": json.dumps(sessions),
            "last_rx": json.dumps(last_rx) if last_rx else None,
            "last_tx": json.dumps(last_tx) if last_tx else None,
            "uptime_24h": self.uptime_24h(),
        }
