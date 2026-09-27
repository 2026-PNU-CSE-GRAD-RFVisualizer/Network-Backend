"""Handheld 로컬 Proxy (구성 B).

핸드헬드 ESP32-S3 와 같은 로컬 WiFi 의 PC(임베디드 노트북)에서 실행
ESP32 는 이 PC 의 로컬 IP
Proxy 가 Tailscale 로 원격 허브에 전달한다.

    핸드헬드 ─UDP 9200─▶ [이 Proxy] ─Tailscale─▶ 허브 Backend 9200
    LCD      ◀─TCP 9102─ [이 Proxy] ◀─Tailscale─ 허브 Relay 9102
"""

from __future__ import annotations

import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("handheld_proxy")


class _UdpForwarder(asyncio.DatagramProtocol):
    """로컬 9200 수신 → 허브 9200 으로 단방향 전달 (핸드헬드 → 백엔드)."""

    def __init__(self, hub: str, hub_port: int) -> None:
        self.hub = (hub, hub_port)
        self.transport: asyncio.DatagramTransport | None = None
        self.out: asyncio.DatagramTransport | None = None
        self.count = 0

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        if self.out is not None:
            self.out.sendto(data, self.hub)
            self.count += 1
            if self.count % 200 == 0:
                logger.info("udp forwarded %d packets → %s:%d", self.count, *self.hub)

async def start_udp(hub: str, hub_port: int, listen: str, local_port: int, loop) -> None:
    proto = _UdpForwarder(hub, hub_port)
    await loop.create_datagram_endpoint(lambda: proto, local_addr=(listen, local_port))
    out_transport, _ = await loop.create_datagram_endpoint(
        lambda: asyncio.DatagramProtocol(), remote_addr=(hub, hub_port))
    proto.out = out_transport
    logger.info("UDP proxy: %s:%d → %s:%d", listen, local_port, hub, hub_port)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def start_tcp(hub: str, hub_port: int, listen: str, local_port: int) -> None:
    async def handle(client_reader, client_writer):
        peer = client_writer.get_extra_info("peername")
        try:
            hub_reader, hub_writer = await asyncio.open_connection(hub, hub_port)
        except Exception as exc:
            logger.warning("hub 연결 실패 %s:%d (%s)", hub, hub_port, exc)
            client_writer.close()
            return
        logger.info("tcp client %s ↔ hub %s:%d 연결", peer, hub, hub_port)
        await asyncio.gather(_pipe(hub_reader, client_writer),
                             _pipe(client_reader, hub_writer))
        logger.info("tcp client %s 종료", peer)

    server = await asyncio.start_server(handle, listen, local_port)
    logger.info("TCP proxy: %s:%d → %s:%d", listen, local_port, hub, hub_port)
    async with server:
        await server.serve_forever()


async def main() -> None:
    p = argparse.ArgumentParser(description="Handheld 로컬 Proxy (UDP 9200 + TCP 9102)")
    p.add_argument("--hub", required=True, help="허브(Network 노트북) Tailscale IP 또는 MagicDNS 이름")
    p.add_argument("--listen", default="0.0.0.0", help="로컬 바인드 주소 (기본 0.0.0.0)")
    p.add_argument("--udp-port", type=int, default=9200, help="Handheld UDP 포트 (기본 9200)")
    p.add_argument("--tcp-port", type=int, default=9102, help="LCD Relay viewer 포트 (기본 9102)")
    args = p.parse_args()

    loop = asyncio.get_running_loop()
    await start_udp(args.hub, args.udp_port, args.listen, args.udp_port, loop)
    logger.info("Proxy 시작 — ESP32 는 이 PC 로컬 IP 로 붙이세요. Ctrl+C 로 종료.")
    await start_tcp(args.hub, args.tcp_port, args.listen, args.tcp_port)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
