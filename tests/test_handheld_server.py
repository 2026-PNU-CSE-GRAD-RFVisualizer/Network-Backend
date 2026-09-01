from __future__ import annotations

import asyncio

from backend.handheld import (
    FLAG_HEIGHT_CYCLE_BUTTON_HELD,
    FLAG_ORIENTATION_VALID,
    FLAG_TELEPORT_BUTTON_HELD,
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

def _provider():
    return ConfiguredPositionProvider(
        frame_id="pnu_3f_corridor_metric_v1",
        positions={"demo-1": {"x": 21.4, "y": 17.8, "z": 1.6, "confidence": 1.0}},
        active="demo-1")

def _svc(hub):
    return HandheldService(hub, _provider(), "pnu_3f_corridor_metric_v1", allowed_device_ids={1})

def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)

def test_orientation_broadcast():
    hub = FakeHub()
    _run(_svc(hub).handle_datagram(
        encode_control_packet(flags=FLAG_ORIENTATION_VALID, device_id=1, session_id=7, sample_seq=1),
        ("192.168.0.9", 5000)))
    s = hub.msgs[-1]
    assert s["type"] == "handheld_state"
    assert s["orientation_valid"] is True
    assert s["device_id"] == "handheld-01"
    assert s["stale"] is False
    assert s["teleport_button_held"] is False
    assert s["height_cycle_button_held"] is False

def test_teleport_button_passthrough():
    hub = FakeHub()
    _run(_svc(hub).handle_datagram(
        encode_control_packet(flags=FLAG_TELEPORT_BUTTON_HELD, device_id=1, session_id=7, sample_seq=1),
        ("192.168.0.9", 5000)))
    s = hub.msgs[-1]
    assert s["teleport_button_held"] is True
    assert s["height_cycle_button_held"] is False

def test_height_cycle_button_passthrough():
    hub = FakeHub()
    _run(_svc(hub).handle_datagram(
        encode_control_packet(flags=FLAG_HEIGHT_CYCLE_BUTTON_HELD, device_id=1, session_id=7, sample_seq=1),
        ("192.168.0.9", 5000)))
    s = hub.msgs[-1]
    assert s["height_cycle_button_held"] is True
    assert s["teleport_button_held"] is False

def test_no_dedup_and_no_position_update():
    hub = FakeHub()
    svc = _svc(hub)
    both = FLAG_TELEPORT_BUTTON_HELD | FLAG_HEIGHT_CYCLE_BUTTON_HELD
    for i in range(3):
        _run(svc.handle_datagram(
            encode_control_packet(flags=both, device_id=1, session_id=7, sample_seq=i + 1),
            ("192.168.0.9", 5000)))
    states = [m for m in hub.msgs if m["type"] == "handheld_state"]
    assert len(states) == 3
    assert all(s["teleport_button_held"] and s["height_cycle_button_held"] for s in states)
    assert not any(m["type"] == "position_update" for m in hub.msgs)

def test_message_has_no_legacy_fields():
    hub = FakeHub()
    _run(_svc(hub).handle_datagram(
        encode_control_packet(flags=FLAG_ORIENTATION_VALID, device_id=1),
        ("192.168.0.9", 5000)))
    s = hub.msgs[-1]
    assert "event_seq" not in s
    assert "recenter_event" not in s
    assert "position_update_event" not in s

def test_device_id_filter():
    hub = FakeHub()
    svc = _svc(hub)
    _run(svc.handle_datagram(
        encode_control_packet(flags=FLAG_ORIENTATION_VALID, device_id=9),
        ("192.168.0.9", 5000)))
    assert svc.metrics.invalid == 1
    assert not hub.msgs

def test_source_ip_filter():
    hub = FakeHub()
    svc = HandheldService(hub, _provider(), "pnu_3f_corridor_metric_v1",
                          allowed_source_ips={"192.168.0.9"})
    _run(svc.handle_datagram(
        encode_control_packet(flags=FLAG_ORIENTATION_VALID, device_id=1),
        ("10.0.0.1", 5000)))
    assert not hub.msgs
    assert svc.metrics.received == 0
