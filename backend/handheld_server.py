"""Handheld Control v1 UDP 수신 서비스 + Graphics WebSocket 브릿지."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .handheld import (
    ControlPacket,
    ControlPacketError,
    EventDeduper,
    SessionTracker,
    normalized_quaternion,
    parse_control_packet,
)
from .position import ConfiguredPositionProvider, PositionProvider, validate_position

logger = logging.getLogger("handheld")

DEVICE_NAME = {1: "handheld-01"}


def now_ms() -> int:
    return int(time.time() * 1000)


def _device_name(device_id: int) -> str:
    return DEVICE_NAME.get(device_id, f"device-{device_id}")


@dataclass
class HandheldMetrics:
    received: int = 0
    invalid: int = 0
    dedup_dropped: int = 0
    position_accepted: int = 0
    position_rejected: int = 0
    stale_transitions: int = 0

    def snapshot(self) -> dict:
        return {
            "received": self.received, "invalid": self.invalid,
            "dedup_dropped": self.dedup_dropped,
            "position_accepted": self.position_accepted,
            "position_rejected": self.position_rejected,
            "stale_transitions": self.stale_transitions,
        }


class HandheldService:
    def __init__(self, hub, provider: PositionProvider, scene_frame_id: str, *,
                 allowed_device_ids: set[int] | None = None,
                 allowed_source_ips: set[str] | None = None,
                 stale_ms: int = 500) -> None:
        self.hub = hub
        self.provider = provider
        self.scene_frame_id = scene_frame_id
        self.allowed_device_ids = allowed_device_ids
        self.allowed_source_ips = allowed_source_ips
        self.stale_ms = stale_ms
        self.dedup = EventDeduper()
        self.sessions = SessionTracker()
        self.metrics = HandheldMetrics()
        self._last_state: dict | None = None
        self._last_valid_ms: int = 0
        self._stale: bool = True

    def latest_state(self) -> dict | None:
        return self._last_state

    def status(self) -> dict:
        return {
            "scene_frame_id": self.scene_frame_id,
            "stale": self._stale,
            "last_valid_ms": self._last_valid_ms,
            "active_position": getattr(self.provider, "active", None),
            "positions": getattr(self.provider, "names", lambda: [])(),
            "metrics": self.metrics.snapshot(),
            "sessions": {sid: vars(s) for sid, s in self.sessions.stats.items()},
        }

    async def handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        if self.allowed_source_ips and addr[0] not in self.allowed_source_ips:
            return
        self.metrics.received += 1
        try:
            p = parse_control_packet(data)
        except ControlPacketError as exc:
            self.metrics.invalid += 1
            logger.debug("invalid packet from %s: %s", addr, exc)
            return
        if self.allowed_device_ids and p.device_id not in self.allowed_device_ids:
            self.metrics.invalid += 1
            return

        self.sessions.observe(p)
        self._last_valid_ms = now_ms()
        self._stale = False

        is_new_event = False
        if p.event_flags():
            is_new_event = self.dedup.is_new(p)
            if not is_new_event:
                self.metrics.dedup_dropped += 1
        recenter_event = is_new_event and p.recenter
        position_update_event = is_new_event and p.request_position_update

        if position_update_event:
            await self._apply_position_update(p)

        state = self._build_state(p, recenter_event, position_update_event, stale=False)
        self._last_state = state
        await self.hub.broadcast(state)

    def _build_state(self, p: ControlPacket, recenter_event: bool,
                     position_update_event: bool, stale: bool) -> dict:
        qx, qy, qz, qw = normalized_quaternion(p)
        return {
            "type": "handheld_state",
            "device_id": _device_name(p.device_id),
            "session_id": p.session_id,
            "sample_seq": p.sample_seq,
            "event_seq": p.event_seq,
            "server_timestamp_ms": now_ms(),
            "orientation_valid": p.orientation_valid,
            "quaternion": {"x": qx, "y": qy, "z": qz, "w": qw},
            "recenter_event": recenter_event,
            "position_update_event": position_update_event,
            "stale": stale,
        }

    async def _apply_position_update(self, p: ControlPacket) -> None:
        pos = self.provider.get_latest()
        ok, reason = validate_position(pos, self.scene_frame_id)
        if ok and pos is not None:
            self.metrics.position_accepted += 1
            msg = {
                "type": "position_update",
                "device_id": _device_name(p.device_id),
                "event_seq": p.event_seq,
                "accepted": True,
                "position": pos.to_message(),
            }
        else:
            self.metrics.position_rejected += 1
            msg = {
                "type": "position_update",
                "device_id": _device_name(p.device_id),
                "event_seq": p.event_seq,
                "accepted": False,
                "position": None,
                "reason": reason,
            }
        await self.hub.broadcast(msg)

    async def watch_stale(self) -> None:
        interval = max(self.stale_ms / 2000.0, 0.05)
        while True:
            await asyncio.sleep(interval)
            if (self._last_state is not None and not self._stale
                    and now_ms() - self._last_valid_ms > self.stale_ms):
                self._stale = True
                self.metrics.stale_transitions += 1
                st = dict(self._last_state)
                st["stale"] = True
                st["server_timestamp_ms"] = now_ms()
                self._last_state = st
                await self.hub.broadcast(st)


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, service: HandheldService, loop: asyncio.AbstractEventLoop) -> None:
        self.service = service
        self.loop = loop

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.loop.create_task(self.service.handle_datagram(data, addr))

    def error_received(self, exc: Exception) -> None:
        logger.debug("udp error: %s", exc)


async def start_udp_listener(service: HandheldService, host: str, port: int,
                             loop: asyncio.AbstractEventLoop):
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _UdpProtocol(service, loop), local_addr=(host, port))
    logger.info("handheld UDP listening on %s:%d", host, port)
    return transport


def load_configured_provider(path: str | Path, default_frame_id: str,
                             default_active: str | None = None,
                             source: str = "configured_demo") -> ConfiguredPositionProvider:
    """JSON 파일에서 시연 좌표를 로드. 파일 없으면 빈 Provider(위치 없음)."""
    p = Path(path)
    if not p.exists():
        logger.warning("handheld positions 파일 없음: %s (위치 미등록)", p)
        return ConfiguredPositionProvider(default_frame_id, source=source)
    data = json.loads(p.read_text(encoding="utf-8"))
    return ConfiguredPositionProvider(
        frame_id=data.get("frame_id", default_frame_id),
        positions=data.get("positions", {}),
        active=data.get("active", default_active),
        source=source,
    )
