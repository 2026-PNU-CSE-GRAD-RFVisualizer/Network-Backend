from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def resolve_path(value: str) -> Path:
    """절대 경로면 그대로, 상대 경로면 프로젝트 루트 기준으로 해석한다."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_host: str = "0.0.0.0"
    app_port: int = 8000

    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None

    database_dsn: str = "postgresql://user:password@127.0.0.1:5432/network"

    enable_realtime: bool = False

    window_size_ms: int = 200
    window_grace_ms: int = 300
    window_flush_interval_ms: int = 50
    node_timeout_seconds: float = 5.0
    timestamp_max_skew_ms: int = 600_000
    rssi_min: int = -110
    rssi_max: int = -10

    experiment_data_dir: str = "data"
    export_root: str = "experiments"
    default_session_seconds: int = 30
    expected_samples_per_point: int = 30
    rssi_filtered_scale: float = 1.0

    test_stabilization_seconds: int = 20
    test_recording_seconds: int = 120
    expected_test_points: int = 10
    expected_calibration_nodes: int = 4

    handheld_enabled: bool = False
    handheld_udp_host: str = "0.0.0.0"
    handheld_udp_port: int = 9200
    handheld_stale_ms: int = 500
    handheld_allowed_device_ids: str = "1"
    handheld_allowed_source_ips: str = ""
    scene_frame_id: str = "pnu_3f_corridor_metric_v1"
    handheld_position_source: str = "configured_demo"
    handheld_positions_file: str = "config/handheld_positions.json"
    handheld_active_position: str | None = None

    def _csv_ints(self, value: str) -> set[int]:
        return {int(v) for v in value.split(",") if v.strip()}

    def _csv_strs(self, value: str) -> set[str]:
        return {v.strip() for v in value.split(",") if v.strip()}

    @property
    def handheld_device_id_set(self) -> set[int]:
        return self._csv_ints(self.handheld_allowed_device_ids)

    @property
    def handheld_source_ip_set(self) -> set[str]:
        return self._csv_strs(self.handheld_allowed_source_ips)

    @property
    def experiment_data_path(self) -> Path:
        return resolve_path(self.experiment_data_dir)

    @property
    def export_root_path(self) -> Path:
        return resolve_path(self.export_root)

settings = Settings()
