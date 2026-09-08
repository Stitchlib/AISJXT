"""第三期 2.2 通知异步化与隔离验收测试。

覆盖验收标准：
- ① webhook 延迟 15s：告警评估（检测循环的同步部分）不阻塞——耗时 < 2s，
   通知在 worker 线程发送，关停 drain 后送达并标记 notified；
- ② 队列打满不崩：丢通知记日志，检测评估继续（事件照常落库）；
- ③ 优雅关停不丢已投递通知：stop() 后全部送达。
"""
import sys
import threading
import time
from pathlib import Path

import pytest

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))

from src.config_manager import ConfigManager  # noqa: E402
from src.database import Database  # noqa: E402
from src.models import DetectionResult  # noqa: E402
from src.notifier import NotificationBus  # noqa: E402
from src import notifier  # noqa: E402


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    yield d
    d._conn.close()


@pytest.fixture
def cm():
    return ConfigManager()


def _hit(rate=0.9) -> DetectionResult:
    return DetectionResult(
        camera_id="cam_sim", defect_rate=rate, defect_count=5, total_count=10,
        processing_time_ms=12.0, is_simulation=True, metric_version=1,
    )


def _rule(db, name="r"):
    rid = db.create_alert_rule({
        "name": name, "metric": "defect_rate", "operator": "gt", "threshold": 0.5,
        "scope": "all", "enabled": True, "webhook_url": "http://hook/local",
        "webhook_type": "generic", "cooldown_seconds": 0,
    })
    return db.get_alert_rule(rid)


def test_slow_webhook_does_not_block_and_drains_on_stop(db, cm, monkeypatch):
    """验收①：webhook 延迟 15s 时评估不阻塞（<2s）；关停 drain 后送达且 notified=1。"""
    captured = []

    def slow_post(url, payload, secret=None, timeout=10):
        time.sleep(15)  # 模拟极慢的外部机器人（验收口径：15s）
        captured.append(payload.get("text") or "")
        return 200

    monkeypatch.setattr(notifier, "_post_json", slow_post)
    _rule(db)
    bus = NotificationBus(db, cm)
    bus.start()
    try:
        t0 = time.perf_counter()
        created = notifier.process_alerts(_hit(), db, cm, bus)
        elapsed = time.perf_counter() - t0
        assert len(created) == 1
        assert elapsed < 2.0, f"慢 webhook 不应阻塞告警评估，实测 {elapsed:.2f}s"
        assert captured == []  # 发送在 worker 中异步进行
        # 优雅关停：等待队列排空（含那条 15s 的慢发送）
        assert bus.stop(timeout=25) is True
        assert len(captured) == 1
        assert db.get_alert_event(created[0])["notified"] == 1
    finally:
        bus.stop(timeout=1)


def test_queue_full_drops_but_evaluation_survives(db, cm, monkeypatch):
    """验收②：队列打满时丢弃并记日志，评估/落库继续、绝不崩。"""
    captured = []
    gate = threading.Event()

    def blocked_post(url, payload, secret=None, timeout=10):
        gate.wait(10)  # 卡住 worker，让队列迅速打满
        captured.append(payload.get("text") or "")
        return 200

    monkeypatch.setattr(notifier, "_post_json", blocked_post)
    _rule(db)
    bus = NotificationBus(db, cm, maxsize=2)
    bus.start()
    try:
        ids = []
        for _ in range(10):
            created = notifier.process_alerts(_hit(rate=0.9), db, cm, bus)
            assert len(created) == 1  # 每帧评估正常、事件照常落库
            ids.extend(created)
        assert len(db.list_alerts(page_size=50)[0]) == 10  # 落库不受影响
        # 队列上限 2 + worker 手里 1 条 = 至多 3 条被受理，必有丢弃
        assert len(captured) == 0
        gate.set()
        bus.stop(timeout=10)
        assert len(captured) <= 3
    finally:
        gate.set()
        bus.stop(timeout=1)


def test_stop_drains_all_pending(db, cm, monkeypatch):
    """验收③：投递 N 条后立即关停，drain 后全部送达且 notified=1。"""
    captured = []

    def quick_post(url, payload, secret=None, timeout=10):
        time.sleep(0.02)
        captured.append(payload.get("text") or "")
        return 200

    monkeypatch.setattr(notifier, "_post_json", quick_post)
    _rule(db)
    bus = NotificationBus(db, cm)
    bus.start()
    ids = []
    for _ in range(20):
        created = notifier.process_alerts(_hit(), db, cm, bus)
        ids.extend(created)
    assert bus.stop(timeout=15) is True
    assert len(captured) == 20
    assert all(db.get_alert_event(i)["notified"] == 1 for i in ids)


def test_recovery_notification_via_bus(db, cm, monkeypatch):
    """恢复通知同样走异步总线：未命中帧投递恢复消息，drain 后送达。"""
    captured = []

    def post(url, payload, secret=None, timeout=10):
        captured.append(payload.get("text") or "")
        return 200

    monkeypatch.setattr(notifier, "_post_json", post)
    _rule(db)
    bus = NotificationBus(db, cm)
    bus.start()
    try:
        notifier.process_alerts(_hit(), db, cm, bus)   # 告警
        notifier.process_alerts(_hit(rate=0.0), db, cm, bus)  # 恢复
        assert bus.stop(timeout=10) is True
        assert any("恢复" in t for t in captured)
        assert len([t for t in captured if "恢复" in t]) == 1
    finally:
        bus.stop(timeout=1)
