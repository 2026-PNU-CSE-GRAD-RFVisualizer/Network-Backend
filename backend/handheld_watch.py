from __future__ import annotations

import argparse
import asyncio
import json
import time

import websockets

class Stats:
    def __init__(self) -> None:
        self.count = 0
        self.gaps = 0
        self.invalid = 0
        self.last_seq: int | None = None
        self.last_session = None
        self.last_q = (0.0, 0.0, 0.0, 1.0)
        self.teleport = False
        self.height = False
        self.stale = True

    def update(self, d: dict) -> None:
        self.count += 1
        session = d.get("session_id")
        seq = d.get("sample_seq")
        if session != self.last_session:
            self.last_seq = None
            self.last_session = session
        if self.last_seq is not None and seq is not None:
            delta = (seq - self.last_seq) & 0xFFFFFFFF
            if 1 < delta < 0x7FFFFFFF:
                self.gaps += delta - 1
        self.last_seq = seq
        q = d["quaternion"]
        self.last_q = (q["x"], q["y"], q["z"], q["w"])
        if not d.get("orientation_valid"):
            self.invalid += 1
        self.teleport = bool(d.get("teleport_button_held"))
        self.height = bool(d.get("height_cycle_button_held"))
        self.stale = bool(d.get("stale"))

async def _summary_loop(st: Stats) -> None:
    prev = 0
    prev_gaps = 0
    while True:
        await asyncio.sleep(1.0)
        rate = st.count - prev
        gap_delta = st.gaps - prev_gaps
        prev, prev_gaps = st.count, st.gaps
        qx, qy, qz, qw = st.last_q
        print(f"[1s] rate={rate:>3} Hz | gap+={gap_delta} (total {st.gaps}) | "
              f"invalid={st.invalid} | teleport={st.teleport} height={st.height} | "
              f"stale={st.stale} | q=({qx:+.3f},{qy:+.3f},{qz:+.3f},{qw:+.3f}) | total={st.count}")

async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://127.0.0.1:8000/handheld/control")
    p.add_argument("--raw", action="store_true", help="매 패킷 상세 출력")
    args = p.parse_args()

    st = Stats()
    print(f"[watch] connecting {args.url} ...")
    async with websockets.connect(args.url) as ws:
        print("[watch] connected. Ctrl+C 로 종료. (1초마다 요약 출력)")
        asyncio.create_task(_summary_loop(st))
        async for msg in ws:
            d = json.loads(msg)
            t = d.get("type")
            if t == "handheld_state":
                st.update(d)
                if args.raw:
                    q = d["quaternion"]
                    print(f"seq={d['sample_seq']:>6} valid={d['orientation_valid']} stale={d['stale']} "
                          f"tp={d.get('teleport_button_held')} hc={d.get('height_cycle_button_held')} "
                          f"q=({q['x']:+.3f},{q['y']:+.3f},{q['z']:+.3f},{q['w']:+.3f})")
            else:
                print(d)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
