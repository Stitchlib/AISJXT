"""第三期 2.1 告警冷却与聚合验收测试。

覆盖验收标准：
- ① 冷却窗口内持续命中只产生 1 条事件（聚合 repeat_count），而非逐帧事件风暴；
- ② cooldown_seconds=0 行为与旧版完全兼容（每次命中新建事件并通知）；
- ③ 聚合事件 repeat_count 正确；冷却结束仍持续 → 持续告警摘要接续；
- ④ 状态恢复：命中→未命中 后事件被关闭且发一次恢复通知（不逐帧重复）；
- ⑤ silence_until 静默窗口完全抑制评估；
- ⑥ 规则 API 暴露/更新 cooldown_seconds（含 0 值语义）与 silence_until 清除。
"""
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))

from src.config_manager import ConfigManager  # noqa: E402
from src.database import Database  # noqa: E402
from src.models import DetectionResult  # noqa: E402
from src import notifier  # noqa: E402


def _login(client, user="admin", pwd="admin123"):
    return client.post("/api/v1/auth/login", json={"username": user, "password": pwd}).json()["access_token"]


def _headers(client, user="admin", pwd="admin123"):
    return {"Authorization": "Bearer " + _login(client, user, pwd)}


class _Capture:
    """捕获 notifier 发出的 webhook 文案，模拟外部机器人接收。"""

    def __init__(self):
        self.texts: list = []
        self._orig = notifier._post_json

    def install(self, monkeypatch):
        def fake_post(url, payload, secret=None, timeout=10):
            self.texts.append(payload.get("text") or "")
            return 200

        monkeypatch.setattr(notifier, "_post_json", fake_post)

    def restore(self):
        notifier._post_json = self._orig


def _hit(rate=0.9, camera_id="cam_sim") -> DetectionResult:
    return DetectionResult(
        camera_id=camera_id, defect_rate=rate, defect_count=5, total_count=10,
        processing_time_ms=12.0, is_simulation=True, metric_version=1,
    )


def _miss(camera_id="cam_sim") -> DetectionResult:
    return _hit(rate=0.0, camera_id=camera_id)


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    yield d
    d._conn.close()


@pytest.fixture
def cm():
    return ConfigManager()


def _rule(db, cooldown=0, name="r", webhook="http://hook/local", scope="all", silence_until=None):
    rid = db.create_alert_rule({
        "name": name, "metric": "defect_rate", "operator": "gt", "threshold": 0.5,
        "scope": scope, "enabled": True, "webhook_url": webhook, "webhook_type": "generic",
        "cooldown_seconds": cooldown, "silence_until": silence_until,
    })
    return db.get_alert_rule(rid)


def test_cooldown_zero_backward_compatible(db, cm, monkeypatch):
    """验收②：cooldown=0 与旧行为一致——每次命中都新建事件并通知。"""
    cap = _Capture()
    cap.install(monkeypatch)
    try:
        _rule(db, cooldown=0)
        for _ in range(5):
            created = notifier.process_alerts(_hit(), db, cm)
            assert len(created) == 1
        events = [e for e in db.list_alerts(page_size=50)[0] if e["rule_id"]]
        assert len(events) == 5
        assert all(e["repeat_count"] == 0 for e in events)
        assert len(cap.texts) == 5  # 每次命中都发了 webhook
    finally:
        cap.restore()


def test_cooldown_aggregates_no_storm(db, cm, monkeypatch):
    """验收①③：冷却窗口内 60 帧持续命中 → 仅 1 条事件，repeat_count=59，只通知 1 次。"""
    cap = _Capture()
    cap.install(monkeypatch)
    try:
        _rule(db, cooldown=300)
        for i in range(60):
            created = notifier.process_alerts(_hit(rate=0.6 + i * 0.001), db, cm)
            assert len(created) == (1 if i == 0 else 0)  # 首帧新建，窗口内不再新建
        events = db.list_alerts(page_size=50)[0]
        assert len(events) == 1
        assert events[0]["repeat_count"] == 59
        assert len(cap.texts) == 1  # 冷却窗口内不再发送
    finally:
        cap.restore()


def test_cooldown_expiry_persistent_summary(db, cm, monkeypatch):
    """验收③续：冷却结束仍持续 → 新事件为"持续告警"摘要并接续关闭旧事件。"""
    cap = _Capture()
    cap.install(monkeypatch)
    try:
        _rule(db, cooldown=1)
        notifier.process_alerts(_hit(), db, cm)  # 第一次命中 → 事件 A
        events = db.list_alerts(page_size=10)[0]
        assert len(events) == 1
        # 把事件 A 时间戳回拨 2 秒，模拟冷却窗口已过（避免真实 sleep）
        conn = sqlite3.connect(db.db_path)
        try:
            back = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
            conn.execute("UPDATE alert_events SET timestamp=?", (back,))
            conn.commit()
        finally:
            conn.close()
        created = notifier.process_alerts(_hit(), db, cm)  # 冷却已过仍命中 → 事件 B
        assert len(created) == 1
        events = db.list_alerts(page_size=10)[0]
        assert len(events) == 2
        b = next(e for e in events if e["id"] == created[0])
        a = next(e for e in events if e["id"] != created[0])
        assert "持续告警" in b["message"]
        assert a["recovered"] == 1  # 旧事件被新事件接续关闭
        assert len(cap.texts) == 2  # 两个事件各通知一次
    finally:
        cap.restore()


def test_recovery_notification_once(db, cm, monkeypatch):
    """验收④：命中后未命中 → 事件关闭 + 恢复通知恰一次；后续未命中不再重复发。"""
    cap = _Capture()
    cap.install(monkeypatch)
    try:
        _rule(db, cooldown=0)
        notifier.process_alerts(_hit(), db, cm)
        alerts_before = len(cap.texts)
        # 第一帧未命中：恢复
        notifier.process_alerts(_miss(), db, cm)
        events = db.list_alerts(page_size=10)[0]
        assert len(events) == 1 and events[0]["recovered"] == 1
        assert events[0]["recovered_at"]
        recovery = [t for t in cap.texts if "恢复" in t]
        assert len(recovery) == 1
        # 后续未命中：无活动事件，不再发恢复通知
        notifier.process_alerts(_miss(), db, cm)
        recovery = [t for t in cap.texts if "恢复" in t]
        assert len(recovery) == 1
        assert alerts_before == 1
    finally:
        cap.restore()


def test_silence_until_suppresses(db, cm, monkeypatch):
    """验收⑤：silence_until 在未来时完全跳过评估（不建事件/不通知/不恢复）。"""
    cap = _Capture()
    cap.install(monkeypatch)
    try:
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        r = _rule(db, cooldown=0, silence_until=future)
        # 静默期命中 → 不建事件不通知
        assert notifier.process_alerts(_hit(), db, cm) == []
        assert cap.texts == []
        # 静默期未命中 → 不触发恢复（本来也没有事件）
        assert notifier.process_alerts(_miss(), db, cm) == []
        # 清除静默后恢复正常
        db.update_alert_rule(r["id"], silence_until=None)
        assert len(notifier.process_alerts(_hit(), db, cm)) == 1
    finally:
        cap.restore()


def test_rule_api_cooldown_fields(client, monkeypatch):
    """验收⑥：规则 API 支持创建带 cooldown_seconds 的规则、更新为 0、清除 silence_until。"""
    h = _headers(client)
    r = client.post("/api/v1/alerts/rules", headers=h, json={
        "name": "cool", "threshold": 0.5, "cooldown_seconds": 300,
        "silence_until": "2099-01-01T00:00:00+00:00",
    })
    assert r.status_code == 201, r.text
    rule = r.json()
    rid = rule["id"]
    assert rule["cooldown_seconds"] == 300
    assert rule["silence_until"] == "2099-01-01T00:00:00+00:00"
    # 更新为 0（关闭冷却）——0 是有效值，不能被 None 过滤吞掉
    r = client.put(f"/api/v1/alerts/rules/{rid}", headers=h, json={"cooldown_seconds": 0})
    assert r.status_code == 200 and r.json()["cooldown_seconds"] == 0
    # 显式 silence_until=null 清除静默
    r = client.put(f"/api/v1/alerts/rules/{rid}", headers=h, json={"silence_until": None})
    assert r.status_code == 200 and r.json()["silence_until"] is None
