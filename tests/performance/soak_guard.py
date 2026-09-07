"""长跑哨兵（SoakGuard）——浸泡/压测的主动故障发现与即停机制。

设计动机（第二期 G8 复盘教训）：
    24h 实跑曾经"跑完了才知道是 FAIL"——harness 的 token 过期、RSS 测量错误、服务卡死
    等问题都要等报告出来才被发现，24 小时白白浪费。本模块把"事后看报告"变成"过程即发现"：

1. **心跳探测**：独立线程按固定间隔（默认 30s）探测，与主采样解耦——5 分钟采样间隔下，
   故障发现延迟从 ≤5min 降到 ≤心跳间隔。
2. **不变量即判**：服务进程存活 / HTTP 可达 / 检测计数持续增长 / RSS 上下限 / P95 上限，
   任一硬指标破坏立即判失败；软指标（HTTP 抖动、P95 偶发）连续 N 次才判失败，避免抖动误杀。
3. **即停即报**：一旦判定失败，立刻置 `abort_reason` 并触发告警回调（webhook / stdout），
   主循环下一拍就收尾退出，不再空跑到 duration 结束。
4. **状态外置**：每次心跳原子写 `--status-file`，任何时刻外部（人或其他会话）可秒级查看
   当前健康度，无需翻日志。

用法：
    guard = SoakGuard(probe=my_probe, alive=lambda: proc.poll() is None,
                      interval_s=30, status_path=Path("soak_status.json"),
                      max_rss_mb=1200, max_rss_growth_pct=25.0, max_p95_ms=3000,
                      max_stall_probes=3, max_consecutive_failures=3)
    guard.start()
    ...
    if guard.abort_reason: 收尾退出
    guard.stop()
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def send_alert(webhook_url: str, title: str, detail: dict, timeout: float = 8.0) -> bool:
    """通用 webhook 告警（与 G3 notifier 的 generic 类型格式一致）。"""
    if not webhook_url:
        return False
    text = f"[AIQC 压测告警] {title}\n```json\n{json.dumps(detail, ensure_ascii=False, indent=2)}\n```"
    payload = json.dumps({"msgtype": "text", "text": {"content": text}}).encode()
    req = urllib.request.Request(webhook_url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError):
        return False


class SoakGuard:
    """心跳哨兵：探测 + 不变量判定 + 即停告警。"""

    def __init__(
        self,
        probe: Callable[[], dict],
        alive: Callable[[], bool] | None = None,
        liveness: Callable[[], bool] | None = None,
        interval_s: float = 30.0,
        status_path: Path | None = None,
        max_rss_mb: float | None = None,
        max_rss_growth_pct: float | None = None,
        max_p95_ms: float | None = None,
        max_stall_probes: int = 3,
        max_consecutive_failures: int = 3,
        max_busy_failures: int = 10,
        webhook_url: str | None = None,
        on_abort: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._probe = probe
        self._alive = alive or (lambda: True)
        # 第二存活信号：HTTP 之外的"服务还在干活"证据（如 DB 仍在写入/图片仍在落盘）。
        # 用于区分「进程死了」与「事件循环被阻塞/过载但流水线仍在推进」——后者要宽限，
        # 不该在几十秒内就判死（24h 实跑曾因此误停）。
        self._liveness = liveness
        self._interval = max(1.0, interval_s)
        self._status_path = Path(status_path) if status_path else None
        self._max_rss_mb = max_rss_mb
        self._max_rss_growth_pct = max_rss_growth_pct
        self._max_p95_ms = max_p95_ms
        self._max_stall_probes = max_stall_probes
        self._max_consecutive_failures = max_consecutive_failures
        self._max_busy_failures = max_busy_failures
        self._webhook_url = webhook_url
        self._on_abort = on_abort

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.abort_reason: str | None = None
        self.aborted_at: str | None = None
        self.probes = 0
        self.baseline_rss_mb: float | None = None
        self.last_count: int | None = None
        self.last: dict = {}
        self.stall_probes = 0
        self.consecutive_failures = 0
        self.busy_failures = 0
        self.max_probe_gap_s = 0.0  # 主机挂起/调度停顿的最大间隔（数据可信度指标）
        self.warnings: list[dict] = []
        self._last_mono: float | None = None
        self._run_id: str = ""

    # ---------- 生命周期 ----------
    def start(self) -> "SoakGuard":
        # 启动即重写状态文件：否则上一轮的 aborted=True 会残留，
        # 外部巡检（人/定时任务）会把"上一次的中止"误读成"本次已中止"。
        self._run_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-pid{os.getpid()}"
        self._write_status(self.snapshot())
        self._thread = threading.Thread(target=self._loop, name="soak-guard", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def __enter__(self) -> "SoakGuard":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # ---------- 查询 ----------
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "run_id": self._run_id,
                "pid": os.getpid(),
                "probes": self.probes,
                "last": self.last,
                "last_count": self.last_count,
                "baseline_rss_mb": self.baseline_rss_mb,
                "stall_probes": self.stall_probes,
                "consecutive_failures": self.consecutive_failures,
                "aborted": self.abort_reason is not None,
                "abort_reason": self.abort_reason,
                "aborted_at": self.aborted_at,
                "busy_failures": self.busy_failures,
                "max_probe_gap_s": round(self.max_probe_gap_s, 1),
                "warnings": self.warnings[-10:],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

    def should_abort(self) -> bool:
        return self.abort_reason is not None

    # ---------- 内部 ----------
    def _write_status(self, snap: dict) -> None:
        if not self._status_path:
            return
        try:
            self._status_path.parent.mkdir(parents=True, exist_ok=True)
            # 原子写：先写临时文件再替换，避免读方读到半截 JSON
            fd, tmp = tempfile.mkstemp(dir=str(self._status_path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._status_path)
        except OSError:
            pass

    def _abort(self, reason: str, snap: dict) -> None:
        with self._lock:
            if self.abort_reason:  # 只记第一个原因，保留首因现场
                return
            self.abort_reason = reason
            self.aborted_at = datetime.now(timezone.utc).isoformat()
            snap = dict(snap, abort_reason=reason, aborted_at=self.aborted_at, aborted=True)
        print(f"[ALERT] SOAK_ABORT reason={reason}", flush=True)
        print(json.dumps(snap, ensure_ascii=False), flush=True)
        if self._webhook_url:
            send_alert(self._webhook_url, reason, snap)
        if self._on_abort:
            try:
                self._on_abort(reason, snap)
            except Exception:
                pass
        self._write_status(snap)

    def _warn(self, kind: str, detail: dict) -> None:
        with self._lock:
            self.warnings.append({"kind": kind, "at": datetime.now(timezone.utc).isoformat(), **detail})
        print(f"[WARN] {kind} {json.dumps(detail, ensure_ascii=False)}", flush=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._stop.wait(self._interval):
                break
            self._tick()
        # 结束时也落一次状态，便于外部确认哨兵已退出
        self._write_status(self.snapshot())

    def _tick(self) -> None:
        # 0) 探测间隔异常检测：主机休眠/调度停顿会让心跳出现远超预期的大间隔，
        #    这期间的数据不可信，必须显式记录，避免把"睡了一觉"误判成服务故障。
        now_mono = time.monotonic()
        if self._last_mono is not None:
            gap = now_mono - self._last_mono
            if gap > self.max_probe_gap_s:
                self.max_probe_gap_s = gap
            if gap > self._interval * 2 + 10:
                self._warn("probe_gap_suspected_host_stall", {
                    "gap_s": round(gap, 1), "expected_s": self._interval,
                    "hint": "主机休眠/系统停顿，该窗口内的采样不计入稳定性结论",
                })
        self._last_mono = now_mono

        # 1) 服务进程存活（硬失败：立即即停）
        try:
            if not self._alive():
                self._abort("server_process_exited", self.snapshot())
                return
        except Exception as e:  # 探测本身异常也算异常信号，但不直接判死
            self._warn("alive_probe_error", {"error": str(e)})

        # 2) 探测（异常归为软失败）
        try:
            snap = self._probe() or {}
        except Exception as e:
            snap = {"http_ok": False, "error": str(e)}
        self.probes += 1

        http_ok = bool(snap.get("http_ok"))
        count = snap.get("total_processed")
        rss = snap.get("rss_mb")
        p95 = snap.get("p95_ms")

        with self._lock:
            self.last = snap
            if self.baseline_rss_mb is None and isinstance(rss, (int, float)) and rss > 0:
                self.baseline_rss_mb = float(rss)
            # 先取旧值再更新：停滞判据必须拿"上一次"的计数比较，
            # 否则 self.last_count 已被本次覆盖，count <= last_count 恒真（假阳性）。
            prev_count = self.last_count
            if isinstance(count, int):
                self.last_count = count

        # 3) 硬失败：RSS 绝对上限 / 相对增长上限（内存泄漏判据，不看绝对波动）
        if isinstance(rss, (int, float)) and rss > 0:
            if self._max_rss_mb and rss > self._max_rss_mb:
                self._abort("rss_ceiling_exceeded", {"rss_mb": rss, "max_rss_mb": self._max_rss_mb, **snap})
                return
            if self._max_rss_growth_pct and self.baseline_rss_mb:
                growth = (rss - self.baseline_rss_mb) / self.baseline_rss_mb * 100
                if growth > self._max_rss_growth_pct:
                    self._abort(
                        "rss_growth_exceeded",
                        {"rss_mb": rss, "baseline_mb": round(self.baseline_rss_mb, 1),
                         "growth_pct": round(growth, 2), "max_pct": self._max_rss_growth_pct},
                    )
                    return

        # 4) 软失败：HTTP 不可达 / P95 超阈值（连续 N 次才判失败）
        soft_fail = False
        if not http_ok:
            soft_fail = True
            self._warn("http_unreachable", {"probes": self.probes})
        if self._max_p95_ms and isinstance(p95, (int, float)) and p95 > self._max_p95_ms:
            soft_fail = True
            self._warn("p95_exceeded", {"p95_ms": p95, "max_p95_ms": self._max_p95_ms})
        # 检测停滞：计数不再增长（引擎卡死/摄像头掉线的关键信号）
        if isinstance(count, int) and prev_count is not None and count <= prev_count:
            self.stall_probes += 1
            self._warn("detection_stalled", {"count": count, "stall_probes": self.stall_probes})
            if self.stall_probes >= self._max_stall_probes:
                self._abort(
                    "detection_stalled_too_long",
                    {"count": count, "stall_probes": self.stall_probes,
                     "window_s": round(self.stall_probes * self._interval, 1)},
                )
                return
        else:
            self.stall_probes = 0

        if soft_fail:
            # 关键分支：HTTP 不通时看"第二存活信号"。
            # 流水线还在推进（DB/图片仍在写）→ 多半是事件循环被阻塞或过载，属于"忙"不是"死"：
            # 只告警、给更长的宽限；只有持续失联到 max_busy_failures 才判失败。
            busy = False
            if self._liveness is not None:
                try:
                    busy = bool(self._liveness())
                except Exception:
                    busy = False
            if busy:
                self.busy_failures += 1
                self._warn("http_unreachable_but_pipeline_alive", {
                    "busy_failures": self.busy_failures,
                    "window_s": round(self.busy_failures * self._interval, 1),
                    "hint": "事件循环阻塞/过载特征（如周期性清理、备份、大结果集查询），非进程死亡",
                })
                if self.busy_failures >= self._max_busy_failures:
                    self._abort(
                        "unresponsive_too_long",
                        {"busy_failures": self.busy_failures,
                         "window_s": round(self.busy_failures * self._interval, 1),
                         "pipeline_alive": True},
                    )
                    return
                self.consecutive_failures = 0
            else:
                self.consecutive_failures += 1
                if self.consecutive_failures >= self._max_consecutive_failures:
                    self._abort(
                        "consecutive_probe_failures",
                        {"consecutive": self.consecutive_failures,
                         "window_s": round(self.consecutive_failures * self._interval, 1),
                         "pipeline_alive": False},
                    )
                    return
        else:
            self.consecutive_failures = 0
            self.busy_failures = 0

        self._write_status(self.snapshot())
