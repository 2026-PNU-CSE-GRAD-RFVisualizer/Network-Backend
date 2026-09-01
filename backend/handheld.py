from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass

MAGIC = 0x52464843
VERSION = 1
PACKET_SIZE = 52

_HEADER = struct.Struct(">IBBHIIIIQffff")
_CRC = struct.Struct(">I")
assert _HEADER.size == 48

FLAG_ORIENTATION_VALID = 1 << 0
FLAG_TELEPORT_BUTTON_HELD = 1 << 1
FLAG_HEIGHT_CYCLE_BUTTON_HELD = 1 << 2
FLAG_TIME_SYNCED = 1 << 3
RESERVED_MASK = 0xF0

QUAT_NORM_MIN = 0.97
QUAT_NORM_MAX = 1.03

class ControlPacketError(Exception):
    pass

def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF

@dataclass
class ControlPacket:
    version: int
    flags: int
    device_id: int
    session_id: int
    sample_seq: int
    event_seq: int
    timestamp_ms: int
    qx: float
    qy: float
    qz: float
    qw: float
    quat_norm: float
    orientation_valid: bool

    @property
    def teleport_button_held(self) -> bool:
        return bool(self.flags & FLAG_TELEPORT_BUTTON_HELD)

    @property
    def height_cycle_button_held(self) -> bool:
        return bool(self.flags & FLAG_HEIGHT_CYCLE_BUTTON_HELD)

    @property
    def time_synced(self) -> bool:
        return bool(self.flags & FLAG_TIME_SYNCED)

def encode_control_packet(*, version: int = VERSION, flags: int = 0, device_id: int = 1,
                          session_id: int = 0, sample_seq: int = 0, event_seq: int = 0,
                          timestamp_ms: int = 0, qx: float = 0.0, qy: float = 0.0,
                          qz: float = 0.0, qw: float = 1.0) -> bytes:
    head = _HEADER.pack(MAGIC, version, flags, PACKET_SIZE, device_id, session_id,
                        sample_seq, event_seq, timestamp_ms, qx, qy, qz, qw)
    return head + _CRC.pack(crc32(head))

def parse_control_packet(data: bytes) -> ControlPacket:
    if len(data) != PACKET_SIZE:
        raise ControlPacketError(f"크기 {len(data)} (기대 {PACKET_SIZE})")
    head = data[:48]
    (magic, version, flags, length, device_id, session_id,
     sample_seq, event_seq, timestamp_ms, qx, qy, qz, qw) = _HEADER.unpack(head)
    got_crc = _CRC.unpack(data[48:52])[0]

    if magic != MAGIC:
        raise ControlPacketError(f"magic 0x{magic:08X}")
    if version != VERSION:
        raise ControlPacketError(f"version {version} (기대 {VERSION})")
    if length != PACKET_SIZE:
        raise ControlPacketError(f"packet_length {length}")
    if flags & RESERVED_MASK:
        raise ControlPacketError(f"reserved bit set: flags=0x{flags:02X}")
    calc_crc = crc32(head)
    if calc_crc != got_crc:
        raise ControlPacketError(f"CRC 불일치: 0x{got_crc:08X} != 0x{calc_crc:08X}")

    finite = all(math.isfinite(v) for v in (qx, qy, qz, qw))
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) if finite else float("nan")
    orient_ok = bool(flags & FLAG_ORIENTATION_VALID) and finite and (QUAT_NORM_MIN <= norm <= QUAT_NORM_MAX)

    return ControlPacket(
        version=version, flags=flags, device_id=device_id, session_id=session_id,
        sample_seq=sample_seq, event_seq=event_seq, timestamp_ms=timestamp_ms,
        qx=qx, qy=qy, qz=qz, qw=qw, quat_norm=norm, orientation_valid=orient_ok,
    )

def normalized_quaternion(p: ControlPacket) -> tuple[float, float, float, float]:
    n = p.quat_norm
    if not math.isfinite(n) or n == 0:
        return (0.0, 0.0, 0.0, 1.0)
    return (p.qx / n, p.qy / n, p.qz / n, p.qw / n)

@dataclass
class SessionStats:
    session_id: int
    received: int = 0
    lost: int = 0
    duplicate: int = 0
    out_of_order: int = 0
    last_sample_seq: int | None = None

class SessionTracker:
    def __init__(self) -> None:
        self.stats: dict[int, SessionStats] = {}

    def observe(self, p: ControlPacket) -> SessionStats:
        s = self.stats.get(p.session_id)
        if s is None:
            s = SessionStats(session_id=p.session_id)
            self.stats[p.session_id] = s
        s.received += 1
        prev = s.last_sample_seq
        cur = p.sample_seq
        if prev is not None:
            delta = (cur - prev) & 0xFFFFFFFF
            if delta == 0:
                s.duplicate += 1
            elif delta > 0x7FFFFFFF:
                s.out_of_order += 1
            elif delta > 1:
                s.lost += delta - 1
        s.last_sample_seq = cur
        return s
