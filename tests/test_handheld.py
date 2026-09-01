from __future__ import annotations

from backend.handheld import (
    FLAG_HEIGHT_CYCLE_BUTTON_HELD,
    FLAG_ORIENTATION_VALID,
    FLAG_TELEPORT_BUTTON_HELD,
    ControlPacketError,
    SessionTracker,
    crc32,
    encode_control_packet,
    parse_control_packet,
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
    assert p.orientation_valid is True

def test_buttons_are_level_passthrough():
    p = parse_control_packet(encode_control_packet(flags=FLAG_TELEPORT_BUTTON_HELD))
    assert p.teleport_button_held is True and p.height_cycle_button_held is False
    p = parse_control_packet(encode_control_packet(flags=FLAG_HEIGHT_CYCLE_BUTTON_HELD))
    assert p.height_cycle_button_held is True and p.teleport_button_held is False
    p = parse_control_packet(encode_control_packet(
        flags=FLAG_TELEPORT_BUTTON_HELD | FLAG_HEIGHT_CYCLE_BUTTON_HELD))
    assert p.teleport_button_held is True and p.height_cycle_button_held is True
    p = parse_control_packet(encode_control_packet(flags=0))
    assert p.teleport_button_held is False and p.height_cycle_button_held is False

def test_reject_bad_magic_version_reserved_crc_size():
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

def test_quaternion_norm_out_of_range_marks_invalid():
    p = parse_control_packet(encode_control_packet(flags=FLAG_ORIENTATION_VALID, qw=2.0))
    assert p.orientation_valid is False

def test_session_tracker_loss_and_dup():
    t = SessionTracker()
    for seq in (1, 2, 4, 4):
        s = t.observe(parse_control_packet(encode_control_packet(session_id=99, sample_seq=seq)))
    assert s.lost == 1
    assert s.duplicate == 1
    assert s.received == 4
