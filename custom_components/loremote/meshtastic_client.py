"""Meshtastic client — T114 serial connection."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Awaitable

from pubsub import pub

_LOGGER = logging.getLogger(__name__)


def test_connection(serial_port: str) -> str:
    """Test connection to T114 and return node ID. Runs in executor."""
    import meshtastic.serial_interface

    iface = None
    try:
        iface = meshtastic.serial_interface.SerialInterface(devPath=serial_port)
        deadline = time.time() + 15
        while time.time() < deadline:
            if iface.myInfo is not None:
                node_num = iface.myInfo.my_node_num
                return f"!{node_num:08x}"
            time.sleep(0.5)
        raise TimeoutError(f"T114 did not initialize within 15s on {serial_port}")
    finally:
        if iface:
            try:
                iface.close()
            except Exception:
                pass


class MeshtasticClient:
    """Manages Serial connection to T114."""

    def __init__(
        self,
        serial_port: str,
        node_id: str | None,
        on_message: Callable[[bytes, str], Awaitable[None]],
        on_connected: Callable = None,
        on_lost: Callable = None,
    ) -> None:
        self._port = serial_port
        self._node_id = node_id
        self._on_message = on_message
        self._on_connected_cb = on_connected
        self._on_lost_cb = on_lost
        self._iface = None
        self._loop = None

    def connect(self) -> None:
        """Connect to T114. Runs in executor."""
        import meshtastic.serial_interface

        _LOGGER.info("LoRemote: connecting to T114 on %s", self._port)
        self._iface = meshtastic.serial_interface.SerialInterface(devPath=self._port)

        deadline = time.time() + 15
        while time.time() < deadline:
            if self._iface.myInfo is not None:
                self._node_id = f"!{self._iface.myInfo.my_node_num:08x}"
                break
            time.sleep(0.5)
        else:
            self._iface.close()
            raise TimeoutError("T114 did not initialize within 15 seconds")

        pub.subscribe(self._on_receive, "meshtastic.receive")
        pub.subscribe(self._on_connected, "meshtastic.connection.established")
        pub.subscribe(self._on_lost, "meshtastic.connection.lost")

        _LOGGER.info("LoRemote: connected to T114, node_id=%s", self._node_id)

    def disconnect(self) -> None:
        """Disconnect from T114. Runs in executor."""
        try:
            pub.unsubscribe(self._on_receive, "meshtastic.receive")
            pub.unsubscribe(self._on_connected, "meshtastic.connection.established")
            pub.unsubscribe(self._on_lost, "meshtastic.connection.lost")
        except Exception:
            pass
        if self._iface:
            try:
                self._iface.close()
            except Exception as e:
                _LOGGER.warning("LoRemote: error closing interface: %s", e)
            self._iface = None
        _LOGGER.info("LoRemote: disconnected from T114")

    def send(self, data: bytes, destination: str, hop_limit: int = 0) -> None:
        """Send binary data to destination node. Runs in executor."""
        if not self._iface:
            _LOGGER.warning("LoRemote: cannot send — not connected")
            return
        from meshtastic.portnums_pb2 import PortNum
        try:
            self._iface.sendData(
                data,
                destinationId=destination,
                portNum=PortNum.PRIVATE_APP,
                wantAck=False,
                hopLimit=hop_limit,
            )
            _LOGGER.debug(
                "LoRemote: sent %d bytes to %s (hop_limit=%d)",
                len(data), destination, hop_limit
            )
        except Exception as e:
            _LOGGER.error("LoRemote: send error: %s", e)

    def set_event_loop(self, loop) -> None:
        """Store asyncio event loop for thread-safe coroutine dispatch."""
        self._loop = loop

    # ── Internal pubsub callbacks ─────────────────────────────────────────

    def _on_receive(self, packet: dict, interface) -> None:
        """Called when a packet arrives from mesh."""
        try:
            decoded = packet.get("decoded", {})
            # portnum может быть строкой "PRIVATE_APP" или числом 256
            portnum = decoded.get("portnum")
            from_node = packet.get("fromId") or f"!{packet.get('from', 0):08x}"

            # DEBUG — логируем все входящие пакеты
            _LOGGER.debug(
                "LoRemote: incoming packet from %s portnum=%s",
                from_node, portnum
            )

            if portnum not in ("PRIVATE_APP", 256):
                return
            payload = decoded.get("payload", b"")
            if not payload:
                return
            rssi = packet.get("rxRssi")
            snr = packet.get("rxSnr")
            # fromId уже строка вида "!a1b2c3d4", from — число
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._on_message(payload, from_node, packet),
                    self._loop,
                )
        except Exception as e:
            _LOGGER.error("LoRemote: error handling received packet: %s", e)

    def _on_connected(self, interface, topic=None) -> None:
        _LOGGER.info("LoRemote: Meshtastic connection established")
        if self._on_connected_cb:
            self._on_connected_cb()

    def _on_lost(self, interface, topic=None) -> None:
        _LOGGER.warning("LoRemote: Meshtastic connection lost — will retry")
        if self._on_lost_cb:
            self._on_lost_cb(topic)
