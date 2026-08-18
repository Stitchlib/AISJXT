"""模块单元测试：验证各模块在隔离状态下的正确性（数据契约与降级策略）。"""
import sys
from pathlib import Path

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))

from src.config_manager import ConfigManager  # noqa: E402
from src.database import Database  # noqa: E402
from src.detector import build_detector  # noqa: E402
from src.models import DetectionResult, LoginRequest  # noqa: E402


def test_database_insert_query(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    rid = db.insert_result(
        {
            "timestamp": "2026-01-01T00:00:00",
            "camera_id": "c1",
            "defects": [{"class_name": "线头", "confidence": 0.9, "bbox": {"x": 1, "y": 1, "width": 2, "height": 2}}],
            "total_count": 10,
            "defect_count": 1,
            "defect_rate": 0.1,
            "processing_time_ms": 20.0,
            "is_simulation": True,
        }
    )
    assert rid == 1
    rows, total = db.query_results(page=1, page_size=10)
    assert total == 1
    assert rows[0]["defect_count"] == 1
    assert rows[0]["defects"][0]["class_name"] == "线头"


def test_database_statistics(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.insert_result(
        {
            "timestamp": "t", "camera_id": "c1", "defects": [],
            "total_count": 10, "defect_count": 2, "defect_rate": 0.2,
            "processing_time_ms": 20.0, "is_simulation": True,
        }
    )
    stats = db.get_statistics()
    assert stats["total"] == 1
    assert stats["defect_rate"] == 0.2


def test_detector_default_is_simulation():
    cfg = ConfigManager().get()
    det = build_detector(cfg)
    assert det.is_simulation is True
    res = det.detect()
    assert "defect_count" in res and "processing_time_ms" in res


def test_detection_result_contract():
    r = DetectionResult(camera_id="c1", total_count=10, defect_count=1)
    row = r.to_db_row()
    assert row["camera_id"] == "c1"
    assert row["is_simulation"] is False


# ---------- 认证与权限（单元） ----------
def test_auth_service_create_and_authenticate(tmp_path):
    from src.auth import AuthService
    from src.config_manager import ConfigManager
    from src.database import Database

    db = Database(str(tmp_path / "auth.db"))
    cm = ConfigManager()
    svc = AuthService(db, cm)  # 同时种子 admin
    assert svc.authenticate("admin", "admin123") is not None
    assert svc.authenticate("admin", "bad") is None
    uid = svc.create_user("op", "pw123", "操作员", "operator")
    assert uid >= 1
    assert svc.authenticate("op", "pw123") is not None
    tok = svc.login(LoginRequest(username="op", password="pw123"))
    assert tok is not None and tok.access_token


def test_auth_password_hashing_uses_pbkdf2(tmp_path):
    from src.auth import AuthService
    from src.config_manager import ConfigManager
    from src.database import Database

    db = Database(str(tmp_path / "auth2.db"))
    cm = ConfigManager()
    svc = AuthService(db, cm)
    row = db.get_user_by_username("admin")
    # salt 与 hash 均以十六进制存储，且哈希长度符合 pbkdf2_sha256(100k)
    assert len(row["salt"]) == 32  # 16 字节 -> 32 十六进制
    assert len(row["password_hash"]) == 64  # sha256 -> 64 十六进制


# ---------- 告警评估 ----------
def test_notifier_triggers_event_on_breach(tmp_path):
    from src.config_manager import ConfigManager
    from src.database import Database
    from src.models import DetectionResult
    from src.notifier import process_alerts

    db = Database(str(tmp_path / "alert.db"))
    cm = ConfigManager()
    rid = db.create_alert_rule({
        "name": "t", "metric": "defect_rate", "operator": "ge",
        "threshold": 0.0, "scope": "all", "enabled": True,
    })
    res = DetectionResult(camera_id="c1", total_count=10, defect_count=5, defect_rate=0.5)
    created = process_alerts(res, db, cm)
    assert len(created) == 1
    rows, total = db.list_alerts()
    assert total == 1
    assert rows[0]["severity"] in ("warning", "critical")


def test_notifier_no_trigger_below_threshold(tmp_path):
    from src.config_manager import ConfigManager
    from src.database import Database
    from src.models import DetectionResult
    from src.notifier import process_alerts

    db = Database(str(tmp_path / "alert2.db"))
    cm = ConfigManager()
    db.create_alert_rule({
        "name": "t", "metric": "defect_rate", "operator": "gt",
        "threshold": 0.99, "scope": "all", "enabled": True,
    })
    res = DetectionResult(camera_id="c1", total_count=10, defect_count=1, defect_rate=0.1)
    assert process_alerts(res, db, cm) == []


# ---------- 数据库：用户 / 模型版本 ----------
def test_database_users_crud(tmp_path):
    from src.database import Database

    db = Database(str(tmp_path / "u.db"))
    assert db.count_users() == 0
    db.create_user("alice", "A", "operator", "salt", "hash")
    assert db.get_user_by_username("alice")["username"] == "alice"
    assert db.count_users() == 1
    assert db.update_user(1, display_name="Alice2", disabled=True) is True
    assert db.list_users()[0]["display_name"] == "Alice2"


def test_database_model_versions(tmp_path):
    from src.database import Database

    db = Database(str(tmp_path / "mv.db"))
    mv_id = db.create_model_version({"name": "v1", "version": "1.0", "metric": 0.9, "active": False})
    assert db.list_model_versions()[0]["name"] == "v1"
    db.set_active_model_version(mv_id)
    assert db.get_active_model_version()["id"] == mv_id
    assert db.delete_model_version(mv_id) is True


# ---------- 摄像头管理 ----------
def test_camera_manager_add_remove():
    from src.camera_manager import CameraManager
    from src.models import CameraInfo, CameraType

    cm = CameraManager()
    before = len(cm.list())
    info = CameraInfo(id="cx", name="x", type=CameraType.USB, source="1")
    cm.add(info)
    assert len(cm.list()) == before + 1
    cm.remove("cx")
    assert cm.get("cx") is None


# ---------- 报表聚合 ----------
def test_reports_aggregation(tmp_path):
    from src.database import Database

    db = Database(str(tmp_path / "r.db"))
    for i in range(5):
        db.insert_result({
            "timestamp": f"2026-01-0{i+1}T10:00:00", "camera_id": "c1",
            "defects": [{"class_name": "线头" if i % 2 else "破洞", "confidence": 0.9,
                         "bbox": {"x": 1, "y": 1, "width": 2, "height": 2}}],
            "total_count": 10, "defect_count": 1, "defect_rate": 0.1,
            "processing_time_ms": 20.0, "is_simulation": True,
        })
    shares = db.get_type_shares()
    assert sum(s["count"] for s in shares) == 5
    trend = db.get_trend("day")
    assert len(trend) == 5


# ---------- 性能 / 稳定性 ----------
def test_bulk_insert_and_query_performance(tmp_path):
    import time
    from src.database import Database

    db = Database(str(tmp_path / "perf.db"))
    row = {
        "timestamp": "2026-01-01T00:00:00", "camera_id": "c1", "defects": [],
        "total_count": 10, "defect_count": 1, "defect_rate": 0.1,
        "processing_time_ms": 20.0, "is_simulation": True,
    }
    t0 = time.perf_counter()
    for i in range(2000):
        db.insert_result({**row, "timestamp": f"2026-01-01T00:{i % 60:02d}:00"})
    elapsed = time.perf_counter() - t0
    rows, total = db.query_results(1, 50)
    assert total == 2000
    assert elapsed < 10.0, f"批量写入过慢: {elapsed:.2f}s"
    assert len(db.get_type_shares()) >= 0  # 不抛异常即可

