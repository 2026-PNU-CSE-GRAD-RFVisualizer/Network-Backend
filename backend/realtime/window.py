"""Time Window 동기화 — 9월 졸업작품 실시간 시각화용.

논문 실험(7/23 강의실 측정)은 위치마다 30초 정지 측정이라 프레임 동기화가 필요 없다.
ENABLE_REALTIME=false 이면 이 모듈은 인스턴스화되지 않는다.

전문가 자문(2026-08) 반영:
- 버킷 기준을 '서버 도착 시각'이 아니라 '노드 측정 시각(timestamp)'으로 바꿨다.
  수집 지연 p95(244ms)가 윈도우(200ms)를 넘으면, 도착 기준 묶음은 실제 측정 구간과
  어긋난다. 측정 시각 기준이면 한 프레임의 값들이 같은 측정 구간에 속함을 보장한다.
- 늦은 도착을 기다리는 유예(grace) 구간을 두어, 지연된 샘플이 자기 버킷에 들어오게 한다.
- 확정(emit)은 측정시각 워터마크 기준(클럭 오프셋에 무관). 스트림이 멈추면 서버 시계
  fallback 으로 강제 확정해 버킷이 영원히 막히지 않게 한다.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class WindowBuffer:
    def __init__(self, window_size_ms: int, grace_ms: int | None = None,
                 stall_flush_ms: int | None = None) -> None:
        self.window_size_ms = window_size_ms
        self.grace_ms = window_size_ms if grace_ms is None else grace_ms
        self.stall_flush_ms = window_size_ms if stall_flush_ms is None else stall_flush_ms

        self.buckets: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._watermark: int | None = None
        self._emitted_before: int | None = None
        self.late_dropped = 0

    def _bucket_of(self, ts: int) -> int:
        return ts - (ts % self.window_size_ms)

    def add(self, measurement: dict[str, Any], receive_ms: int) -> None:
        meas_ts = measurement.get("timestamp")
        if meas_ts is None:
            meas_ts = receive_ms
        bucket_ts = self._bucket_of(meas_ts)

        if self._emitted_before is not None and bucket_ts <= self._emitted_before:
            self.late_dropped += 1
            return

        self._watermark = meas_ts if self._watermark is None else max(self._watermark, meas_ts)

        node_id = measurement["node_id"]
        current = self.buckets[bucket_ts].get(node_id)
        if current is None or meas_ts >= current["_meas_ts"]:
            item = dict(measurement)
            item["_meas_ts"] = meas_ts
            item["_receive_ms"] = receive_ms
            self.buckets[bucket_ts][node_id] = item

    def pop_ready(self, current_ms: int, known_nodes: set[str]) -> list[dict[str, Any]]:
        event_ready = (self._watermark - self.window_size_ms - self.grace_ms
                       if self._watermark is not None else None)
        wall_ready = current_ms - self.window_size_ms - self.grace_ms - self.stall_flush_ms
        ready_before = wall_ready if event_ready is None else max(event_ready, wall_ready)

        frames: list[dict[str, Any]] = []
        for bucket_ts in sorted(list(self.buckets)):
            if bucket_ts > ready_before:
                continue
            bucket = self.buckets.pop(bucket_ts)
            self._emitted_before = (bucket_ts if self._emitted_before is None
                                    else max(self._emitted_before, bucket_ts))
            nodes = {
                node_id: {
                    "rssi": item["rssi"],
                    "ap_bssid": item.get("ap_bssid"),
                    "seq": item.get("seq"),
                    "node_ts": item.get("timestamp"),
                    "server_receive_ms": item["_receive_ms"],
                    "pos": {"x": item.get("pos_x"), "y": item.get("pos_y"), "z": item.get("pos_z")},
                    "rot": {"w": item.get("rot_w"), "x": item.get("rot_x"),
                            "y": item.get("rot_y"), "z": item.get("rot_z")},
                }
                for node_id, item in sorted(bucket.items())
            }
            frames.append(
                {
                    "type": "rssi_frame",
                    "window_ts": bucket_ts,
                    "window_size_ms": self.window_size_ms,
                    "grace_ms": self.grace_ms,
                    "nodes": nodes,
                    "missing": sorted(known_nodes - set(nodes)),
                }
            )
        return frames
