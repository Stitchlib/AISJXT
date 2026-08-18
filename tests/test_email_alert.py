"""邮件告警链路测试（自包含、零外部依赖、可离线运行）。

不依赖任何真实 SMTP 服务：测试内启动一个极简 SMTP 接收服务（asyncio 实现，
仅用于回显并捕获邮件），真实调用 `notifier.send_email` 与 `notifier.process_alerts`，
验证：
- 邮件经 SMTP 真实收发，收件人/主题/正文正确；
- 告警规则命中时落库事件 + 发送邮件 + 标记 notified 全链路打通。

使用轻量 ConfigManager 包装（不调用 .update()，避免改写仓库 config.json）。
"""
import asyncio
import smtplib
import sys
import threading
import time
from email.parser import BytesParser
import email.policy
from pathlib import Path

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))

from src.config_manager import AppConfig  # noqa: E402
from src.database import Database  # noqa: E402
from src.notifier import process_alerts, send_email  # noqa: E402
from src.models import DetectionResult  # noqa: E402


class _Cfg:
    """最小化 ConfigManager 接口包装，仅用于测试，不落盘。"""

    def __init__(self, **kw):
        self._c = AppConfig(**kw)

    def get(self):
        return self._c


class _SmtpCapture:
    """极简 SMTP 服务：回显命令并捕获接收到的邮件。"""

    def __init__(self):
        self.messages = []
        self.port = 0
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._stop = threading.Event()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(10)

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = server.sockets[0].getsockname()[1]
        self._ready.set()
        async with server:
            while not self._stop.is_set():
                await asyncio.sleep(0.05)

    async def _handle(self, reader, writer):
        async def send(line):
            writer.write((line + "\r\n").encode())
            await writer.drain()

        await send("220 test-smtp ready")
        recv = {"from": None, "to": [], "data": b""}
        in_data = False
        try:
            while not self._stop.is_set():
                line = (await reader.readline()).decode("utf-8", "replace")
                if not line:
                    break
                if in_data:
                    if line == ".\r\n":
                        in_data = False
                        msg = BytesParser(policy=email.policy.default).parsebytes(recv["data"])
                        self.messages.append(
                            {
                                "from": recv["from"],
                                "to": recv["to"],
                                "subject": msg["subject"],
                                "body": msg.get_payload(),
                            }
                        )
                        await send("250 OK: queued")
                    else:
                        recv["data"] += line.encode()
                    continue
                cmd = line.strip().split(" ", 1)[0].upper()
                if cmd in ("EHLO", "HELO"):
                    await send("250-testserver")
                    await send("250 AUTH LOGIN PLAIN")
                elif cmd == "AUTH":
                    await send("334 VXNlcm5hbWU6")  # base64 "Username:"
                    await reader.readline()  # 客户端用户名
                    await send("334 UGFzc3dvcmQ6")  # base64 "Password:"
                    await reader.readline()  # 客户端密码
                    await send("235 Authenticated")
                elif cmd == "MAIL":
                    recv["from"] = line.split(":", 1)[1].strip().strip("<>")
                    await send("250 OK")
                elif cmd == "RCPT":
                    recv["to"].append(line.split(":", 1)[1].strip().strip("<>"))
                    await send("250 OK")
                elif cmd == "DATA":
                    await send("354 End data with <CR><LF>.<CR><LF>")
                    in_data = True
                elif cmd == "QUIT":
                    await send("221 Bye")
                    break
                else:
                    await send("250 OK")
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def stop(self):
        self._stop.set()


def _make_cfg(smtp_port: int, **extra):
    return _Cfg(
        smtp_enabled=True,
        smtp_host="127.0.0.1",
        smtp_port=smtp_port,
        smtp_mode="plain",
        smtp_user="tester",
        smtp_pass="secret",
        smtp_from="aiqc@noreply.local",
        **extra,
    )


def test_send_email_real_smtp_roundtrip():
    srv = _SmtpCapture()
    srv.start()
    try:
        cm = _make_cfg(srv.port)
        ok = send_email(cm, "ops@example.com", "质检告警-高瑕疵率", "摄像头 cam_001 瑕疵率 0.500")
        assert ok is True
        assert len(srv.messages) == 1
        m = srv.messages[0]
        assert m["to"] == ["ops@example.com"]
        assert m["subject"] == "质检告警-高瑕疵率"
        assert "cam_001" in m["body"]
        assert m["from"] == "aiqc@noreply.local"
    finally:
        srv.stop()


def test_send_email_disabled_returns_false():
    srv = _SmtpCapture()
    srv.start()
    try:
        cm = _Cfg(smtp_enabled=False, smtp_host="127.0.0.1", smtp_port=srv.port)
        assert send_email(cm, "ops@example.com", "x", "y") is False
        assert srv.messages == []
    finally:
        srv.stop()


def test_process_alerts_creates_event_and_emails(tmp_path):
    srv = _SmtpCapture()
    srv.start()
    try:
        db = Database(str(tmp_path / "alert_test.db"))
        cm = _make_cfg(srv.port)
        db.create_alert_rule(
            {
                "name": "高瑕疵率预警",
                "metric": "defect_rate",
                "operator": "gt",
                "threshold": 0.1,
                "scope": "all",
                "enabled": True,
                "notify_email": "ops@example.com",
            }
        )
        # 一次会触发规则的真实检测结果（非仿真，瑕疵率 0.5 > 0.1）
        result = DetectionResult(
            camera_id="cam_001",
            defects=[],
            total_count=10,
            defect_count=5,
            defect_rate=0.5,
            processing_time_ms=100.0,
            is_simulation=False,
        )
        ids = process_alerts(result, db, cm)
        assert ids, "应创建告警事件"
        assert len(srv.messages) == 1, "应发送一封告警邮件"
        assert srv.messages[0]["to"] == ["ops@example.com"]

        events, _total = db.list_alerts(acknowledged=None)
        assert events, "告警事件应落库"
        assert events[0]["notified"] == 1, "命中邮件通知后应标记 notified=1"
        assert events[0]["severity"] == "critical"
    finally:
        srv.stop()
