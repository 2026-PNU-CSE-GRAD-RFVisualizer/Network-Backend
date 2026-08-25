"""핸드헬드 Control WS 확인 도구.

백엔드 WS /handheld/control 에 붙어 실시간 quaternion·이벤트를 출력한다.
자이로(BNO085) UDP 시험 때, 센서를 돌리면 값이 바뀌는지 눈으로 확인용.

    py handheld_watch.py
    py handheld_watch.py --url ws://100.85.80.106:8000/handheld/control
"""

from __future__ import annotations

import argparse
import asyncio
import json

import websockets


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://127.0.0.1:8000/handheld/control")
    args = p.parse_args()

    print(f"[watch] connecting {args.url} ...")
    async with websockets.connect(args.url) as ws:
        print("[watch] connected. Ctrl+C 로 종료.")
        async for msg in ws:
            d = json.loads(msg)
            t = d.get("type")
            if t == "handheld_state":
                q = d["quaternion"]
                flags = []
                if d.get("recenter_event"): flags.append("RECENTER")
                if d.get("position_update_event"): flags.append("POS_UPDATE")
                if d.get("stale"): flags.append("STALE")
                print(f"seq={d['sample_seq']:>6} valid={str(d['orientation_valid']):5} "
                      f"q=({q['x']:+.3f},{q['y']:+.3f},{q['z']:+.3f},{q['w']:+.3f}) "
                      + (" ".join(flags)))
            elif t == "position_update":
                print(f"[position_update] accepted={d['accepted']} "
                      f"{d.get('position') or d.get('reason')}")
            else:
                print(d)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
