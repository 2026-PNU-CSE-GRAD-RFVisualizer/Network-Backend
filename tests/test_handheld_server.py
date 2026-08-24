"""HandheldService(UDP 처리 + WS 브릿지 로직) 통합 테스트. fastapi 불필요."""

from __future__ import annotations

import asyncio

from backend.handheld import (
    FLAG_ORIENTATION_VALID,
    FLAG_RECENTER_ORIENTATION,
    FLAG_REQUEST_POSITION_UPDATE,
    encode_control_packet,
)
from backend.handheld_server import HandheldService
from backend.position import ConfiguredPositionProvider


class FakeHub:
    def __init__(self) -> None:
        self.msgs: list[dict] = []

    async def broadcast(self, m: dict) -> None:
        self.msgs.append(m)

    async def send(self, ws, m: dict) -> None:
        self.msgs.append(m)


def _provider(frame_id="experiment-room-v1"):
    return ConfiguredPositionProvider(
        frame_id=frame_id,
        positions={"demo-1": {"x": 1.25, "y": 3.40, "z": 1.20, "confidence": 0.9},
                   "demo-2": {"x": 5.0, "y": 2.0, "z": 1.0, "confidence": 0.9}},
        active="demo-1")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_orientation_broadcast():
    hub = FakeHub()
    svc = HandheldService(hub, _provider(), "experiment-room-v1", allowed_device_ids={1})
    _run(svc.handle_datagram(
        encode_control_packet(flags=FLAG_ORIENTATION_VALID, device_id=1, session_id=7, sample_seq=1),
        ("192.168.0.9", 5000)))
    s = hub.msgs[-1]
    assert s["type"] == "handheld_state"
    assert s["orientation_valid"] is True
    assert s["device_id"] == "handheld-01"
    assert s["stale"] is False


def test_position_update_dedup_once_and_accepted():
    hub = FakeHub()
    svc = HandheldService(hub, _provider(), "experiment-room-v1", allowed_device_ids={1})
    pkt = encode_control_packet(flags=FLAG_REQUEST_POSITION_UPDATE, device_id=1,
                                session_id=7, sample_seq=2, event_seq=1)
    for _ in range(3):
        _run(svc.handle_datagram(pkt, ("192.168.0.9", 5000)))
    pu = [m for m in hub.msgs if m["type"] == "position_update"]
    assert len(pu) == 1
    assert pu[0]["accepted"] is True
    assert pu[0]["position"]["x"] == 1.25
    assert svc.metrics.dedup_dropped == 2


def test_frame_mismatch_rejected():
    hub = FakeHub()
    svc = HandheldService(hub, _provider(), "other-scene", allowed_device_ids={1})
    pkt = encode_control_packet(flags=FLAG_REQUEST_POSITION_UPDATE, device_id=1,
                                session_id=7, sample_seq=2, event_seq=1)
    _run(svc.handle_datagram(pkt, ("192.168.0.9", 5000)))
    pu = [m for m in hub.msgs if m["type"] == "position_update"][0]
    assert pu["accepted"] is False
    assert pu["reason"] == "frame_mismatch"


def test_recenter_event_flag():
    hub = FakeHub()
    svc = HandheldService(hub, _provider(), "experiment-room-v1", allowed_device_ids={1})
    pkt = encode_control_packet(flags=FLAG_RECENTER_ORIENTATION | FLAG_ORIENTATION_VALID,
                                device_id=1, session_id=7, sample_seq=2, event_seq=1)
    _run(svc.handle_datagram(pkt, ("192.168.0.9", 5000)))
    s = hub.msgs[-1]
    assert s["recenter_event"] is True


def test_device_id_filter():
    hub = FakeHub()
    svc = HandheldService(hub, _provider(), "experiment-room-v1", allowed_device_ids={1})
    _run(svc.handle_datagram(
        encode_control_packet(flags=FLAG_ORIENTATION_VALID, device_id=9, session_id=7),
        ("192.168.0.9", 5000)))
    assert svc.metrics.invalid == 1
    assert not hub.msgs


def test_source_ip_filter():
    hub = FakeHub()
    svc = HandheldService(hub, _provider(), "experiment-room-v1",
                          allowed_source_ips={"192.168.0.9"})
    _run(svc.handle_datagram(
        encode_control_packet(flags=FLAG_ORIENTATION_VALID, device_id=1),
        ("10.0.0.1", 5000)))
    assert not hub.msgs
    assert svc.metrics.received == 0
