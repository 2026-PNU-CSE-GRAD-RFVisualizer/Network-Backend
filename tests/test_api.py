"""FastAPI 통합 테스트

FastAPI/httpx 가 설치된 환경(venv)에서만 실행된다:
    py -m pytest tests/test_api.py -q

핵심 회귀:
- /experiment/end 가 500 이 아니라 200 (end_experiment 보충)
- 사전 Offset 없이 /run/start 는 409
- 구 /session/* 는 410 Gone
- Run 없이 /test-segment/prepare 는 409
- 실행 중 새 실험 시작이 이전 열린 Run 을 interrupted 로 정리
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def client():
    tmp = tempfile.mkdtemp()
    os.environ["EXPERIMENT_DATA_DIR"] = str(Path(tmp) / "data")
    os.environ["EXPORT_ROOT"] = str(Path(tmp) / "experiments")
    os.environ["ENABLE_REALTIME"] = "false"
    import importlib
    import backend.config as cfg
    importlib.reload(cfg)
    import backend.main as main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c


def _new_exp(client) -> str:
    r = client.post("/experiment/start", json={"experiment_id": f"api_{int(time.time()*1000)}"})
    assert r.status_code == 200
    return r.json()["experiment_id"]


def test_experiment_end_not_500(client):
    _new_exp(client)
    r = client.post("/experiment/end")
    assert r.status_code == 200
    assert r.json()["ended"] is True


def test_run_start_requires_pre_offset(client):
    _new_exp(client)
    r = client.post("/run/start", json={"direction": "forward", "pass_index": 1})
    assert r.status_code == 409


def test_legacy_session_gone(client):
    for path in ("/session/start", "/session/stop"):
        assert client.post(path).status_code == 410
    assert client.get("/session/current").status_code == 410


def test_segment_without_run_conflict(client):
    _new_exp(client)
    r = client.post("/test-segment/prepare",
                    json={"point_id": "T1", "order_index": 1,
                          "stabilization_seconds": 0, "recording_seconds": 5})
    assert r.status_code == 409


def test_bad_pass_index_rejected(client):
    _new_exp(client)
    r = client.post("/run/start", json={"direction": "forward", "pass_index": 0})
    assert r.status_code in (400, 409)


def test_new_experiment_interrupts_open_runs(client):
    exp = _new_exp(client)
    for i, pt in enumerate(["C1", "C2", "C3", "C4"], start=1):
        client.post("/experiment/assign", json={"node_id": f"node-0{i}", "point_id": pt, "point_role": "calibration"})
    client.post("/experiment/assign", json={"node_id": "node-05", "point_id": "T-move", "point_role": "test"})
    import backend.main as main
    off = main.sessions.start_offset_run("pre")
    for n in ["node-01", "node-02", "node-03", "node-04", "node-05"]:
        ctx = main.sessions.offset_context(n)
        main.store.insert_measurements([{
            "experiment_id": exp, "session_id": ctx["run_id"], "run_id": ctx["run_id"],
            "segment_id": None, "point_id": ctx["point_id"], "point_role": "offset",
            "node_id": n, "server_ts_ms": 1, "rssi_filtered_dbm": -60.0, "valid": True}])
    main.sessions.stop_offset_run()
    from backend.experiment import compute_device_offsets
    compute_device_offsets(main.store, exp, off["offset_run_id"])

    assert client.post("/run/start", json={"direction": "forward", "pass_index": 1}).status_code == 200
    r = client.post("/experiment/start", json={"experiment_id": "api_second"})
    assert r.status_code == 200
    assert r.json()["interrupted"]["runs"] >= 1
