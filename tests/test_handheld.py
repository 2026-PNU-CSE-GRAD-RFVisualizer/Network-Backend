"""Handheld Control v1 (RFHC) 파서·CRC·Position 단위 테스트."""

from __future__ import annotations

from backend.handheld import (
    FLAG_ORIENTATION_VALID,
    FLAG_REQUEST_POSITION_UPDATE,
    ControlPacketError,
    EventDeduper,
    SessionTracker,
    crc32,
    encode_control_packet,
    parse_control_packet,
)
from backend.position import (
    REASON_FRAME_MISMATCH,
    REASON_LOW_CONFIDENCE,
    REASON_NO_POSITION,
    REASON_STALE,
    ConfiguredPositionProvider,
    validate_position,
)

SHARED_VECTOR_HEX = (
    "52464843010100340000000112345678000000010000000000000000"
    "000000000000000000000000000000003F8000000AE927E5"
)
SHARED_CRC = 0x0AE927E5


def test_crc_method_matches_spec():
    assert crc32(b"123456789") == 0xCBF43926


def test_shared_vector_bytes_and_crc():
    pkt = encode_control_packet(
        version=1, flags=FLAG_ORIENTATION_VALID, device_id=1, session_id=0x12345678,
        sample_seq=1, event_seq=0, timestamp_ms=0, qx=0.0, qy=0.0, qz=0.0, qw=1.0,
    )
    assert pkt.hex().upper() == SHARED_VECTOR_HEX
    assert crc32(pkt[:48]) == SHARED_CRC


def test_parse_shared_vector():
    p = parse_control_packet(bytes.fromhex(SHARED_VECTOR_HEX))
    assert p.version == 1
    assert p.device_id == 1
    assert p.session_id == 0x12345678
    assert p.sample_seq == 1
    assert p.orientation_valid is True
    assert abs(p.quat_norm - 1.0) < 1e-6
    assert (p.qx, p.qy, p.qz, p.qw) == (0.0, 0.0, 0.0, 1.0)


def test_reject_bad_magic_version_length_reserved_crc():
    good = bytearray(encode_control_packet(flags=FLAG_ORIENTATION_VALID))
    b = bytearray(good); b[0] ^= 0xFF
    _expect_error(bytes(b))
    b = bytearray(good); b[4] = 2
    _expect_error(bytes(b))
    b = bytearray(good); b[5] |= 0x10
    _expect_error(bytes(b))
    b = bytearray(good); b[16] ^= 0x01
    _expect_error(bytes(b))
    _expect_error(bytes(good[:-1]))


def _expect_error(data: bytes):
    try:
        parse_control_packet(data)
    except ControlPacketError:
        return
    raise AssertionError("ControlPacketError 를 기대했는데 통과함")


def test_quaternion_norm_out_of_range_marks_invalid_not_reject():
    p = parse_control_packet(encode_control_packet(
        flags=FLAG_ORIENTATION_VALID, qx=0.0, qy=0.0, qz=0.0, qw=2.0))
    assert p.orientation_valid is False


def test_event_dedup_three_repeats_once():
    dd = EventDeduper()
    p = parse_control_packet(encode_control_packet(
        flags=FLAG_REQUEST_POSITION_UPDATE, device_id=1, session_id=7, event_seq=3))
    assert dd.is_new(p) is True
    assert dd.is_new(p) is False
    assert dd.is_new(p) is False
    p2 = parse_control_packet(encode_control_packet(
        flags=FLAG_REQUEST_POSITION_UPDATE, device_id=1, session_id=7, event_seq=4))
    assert dd.is_new(p2) is True


def test_session_tracker_loss_and_dup():
    t = SessionTracker()
    for seq in (1, 2, 4, 4):
        p = parse_control_packet(encode_control_packet(session_id=99, sample_seq=seq))
        s = t.observe(p)
    assert s.lost == 1
    assert s.duplicate == 1
    assert s.received == 4


def test_configured_position_provider_and_validation():
    prov = ConfiguredPositionProvider(
        frame_id="experiment-room-v1",
        positions={"A": {"x": 1.25, "y": 3.40, "z": 1.20},
                   "B": {"x": 5.0, "y": 2.0, "z": 1.0}},
        active="A",
    )
    pos = prov.get_latest()
    assert pos is not None and pos.position_x == 1.25 and pos.source == "configured_demo"
    ok, reason = validate_position(pos, "experiment-room-v1")
    assert ok and reason is None
    ok, reason = validate_position(pos, "other-scene")
    assert not ok and reason == REASON_FRAME_MISMATCH
    prov.set_active("B")
    assert prov.get_latest().position_x == 5.0


def test_position_rejects():
    from backend.position import Position, now_ms
    assert validate_position(None, "f")[1] == REASON_NO_POSITION
    stale = Position(now_ms() - 5000, "f", 1, 1, 1, 0.9, "valid", "x")
    assert validate_position(stale, "f")[1] == REASON_STALE
    low = Position(now_ms(), "f", 1, 1, 1, 0.1, "valid", "x")
    assert validate_position(low, "f")[1] == REASON_LOW_CONFIDENCE


def test_reject_zero_placeholder():
    try:
        ConfiguredPositionProvider("f", positions={"z": {"x": 0.0, "y": 0.0, "z": 0.0}})
    except ValueError:
        return
    raise AssertionError("(0,0,0) 는 거부되어야 함")
