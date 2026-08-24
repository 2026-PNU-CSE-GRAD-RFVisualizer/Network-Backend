"""위치 출처 추상화. ConfiguredPositionProvider(설정 좌표) → 이후 추정 Provider 로 교체."""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

REASON_NO_POSITION = "no_position"
REASON_STALE = "stale_position"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_FRAME_MISMATCH = "frame_mismatch"
REASON_INVALID = "invalid_position"

DEFAULT_MAX_AGE_MS = 2000
DEFAULT_MIN_CONFIDENCE = 0.5


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Position:
    timestamp: int
    frame_id: str
    position_x: float
    position_y: float
    position_z: float
    confidence: float
    status: str
    source: str

    def to_message(self) -> dict:
        return {
            "frame_id": self.frame_id,
            "x": self.position_x, "y": self.position_y, "z": self.position_z,
            "confidence": self.confidence, "source": self.source,
        }


class PositionProvider(ABC):
    @abstractmethod
    def get_latest(self) -> Position | None:
        ...


class ConfiguredPositionProvider(PositionProvider):
    def __init__(self, frame_id: str, positions: dict[str, dict] | None = None,
                 active: str | None = None, source: str = "configured_demo") -> None:
        self.frame_id = frame_id
        self.source = source
        self._positions: dict[str, tuple[float, float, float, float]] = {}
        self._active: str | None = None
        for name, p in (positions or {}).items():
            self.add(name, p["x"], p["y"], p["z"], p.get("confidence", 1.0))
        if active:
            self.set_active(active)
        elif self._positions:
            self._active = next(iter(self._positions))

    def add(self, name: str, x: float, y: float, z: float, confidence: float = 1.0) -> None:
        if x == 0.0 and y == 0.0 and z == 0.0:
            raise ValueError("(0,0,0) placeholder 는 등록할 수 없습니다.")
        if not all(math.isfinite(v) for v in (x, y, z)):
            raise ValueError("좌표는 finite 여야 합니다.")
        self._positions[name] = (float(x), float(y), float(z), float(confidence))

    def set_active(self, name: str) -> None:
        if name not in self._positions:
            raise KeyError(f"등록되지 않은 위치: {name}")
        self._active = name

    def names(self) -> list[str]:
        return list(self._positions)

    @property
    def active(self) -> str | None:
        return self._active

    def get_latest(self) -> Position | None:
        if self._active is None:
            return None
        x, y, z, conf = self._positions[self._active]
        return Position(
            timestamp=now_ms(), frame_id=self.frame_id,
            position_x=x, position_y=y, position_z=z,
            confidence=conf, status="valid", source=self.source,
        )


def validate_position(pos: Position | None, scene_frame_id: str, *,
                      now: int | None = None, max_age_ms: int = DEFAULT_MAX_AGE_MS,
                      min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> tuple[bool, str | None]:
    if pos is None:
        return False, REASON_NO_POSITION
    if pos.status != "valid":
        return False, REASON_INVALID
    if not all(math.isfinite(v) for v in (pos.position_x, pos.position_y, pos.position_z)):
        return False, REASON_INVALID
    ts_now = now if now is not None else now_ms()
    if ts_now - pos.timestamp > max_age_ms:
        return False, REASON_STALE
    if pos.confidence < min_confidence:
        return False, REASON_LOW_CONFIDENCE
    if pos.frame_id != scene_frame_id:
        return False, REASON_FRAME_MISMATCH
    return True, None
