"""SoakGuard 单测：长跑哨兵的判定必须秒级可验证，不能再靠几小时实跑暴露假阳性。

覆盖：健康不误杀、进程退出即停、计数停滞即停、RSS 越限即停、瞬时抖动不误杀、
连续软失败即停、状态文件可解析、首因保留。
"""
from __future__ import annotations

import json
import time


from soak_guard import SoakGuard


def _make_probe(script: list[dict]):
    """按调用次数返回预设响应，用尽后重复最后一个。"""
    calls = {"n": 0}

    def probe() -> dict:
        i = min(calls["n"], len(script) - 1)
        calls["n"] += 1
        return dict(script[i])

    return probe, calls


def _ok(count: int, rss: float = 400.0, p95: float = 300.0) -> dict:
    return {"http_ok": True, "total_processed": count, "rss_mb": rss, "p95_ms": p95}


def _wait(guard: SoakGuard, timeout: float = 8.0) -> bool:
    """等哨兵判定（或超时）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if guard.should_abort():
            return True
        time.sleep(0.1)
    return guard.should_abort()


def test_healthy_run_never_aborts(tmp_path):
    """检测计数持续增长：不触发任何即停，状态文件健康。"""
    probe, _ = _make_probe([_ok(1), _ok(2), _ok(3), _ok(4), _ok(5)])
    # 用递增生成器替代固定脚本
    state = {"c": 0}

    def counting_probe():
        state["c"] += 1
        return _ok(state["c"])

    status = tmp_path / "status.json"
    with SoakGuard(probe=counting_probe, alive=lambda: True, interval_s=1.0,
                   status_path=status, max_stall_probes=3) as g:
        time.sleep(3.5)
        assert not g.should_abort(), g.snapshot()
        assert g.probes >= 2
        assert g.stall_probes == 0
    snap = json.loads(status.read_text(encoding="utf-8"))
    assert snap["aborted"] is False and snap["probes"] >= 2


def test_server_exit_aborts_immediately(tmp_path):
    """服务进程退出：立即即停（硬失败，不看连续次数）。"""
    with SoakGuard(probe=lambda: _ok(1), alive=lambda: False, interval_s=1.0,
                   status_path=tmp_path / "s.json") as g:
        assert _wait(g), "服务进程退出未被哨兵发现"
        assert g.abort_reason == "server_process_exited"


def test_detection_stall_aborts(tmp_path):
    """计数连续 N 次不增长：判定引擎卡死/摄像头掉线。"""
    with SoakGuard(probe=lambda: _ok(42), alive=lambda: True, interval_s=1.0,
                   status_path=tmp_path / "s.json", max_stall_probes=3) as g:
        assert _wait(g), "检测停滞未被哨兵发现"
        assert g.abort_reason == "detection_stalled_too_long"
        assert g.snapshot()["last_count"] == 42


def test_rss_ceiling_and_growth_abort(tmp_path):
    """RSS 绝对上限与相对增长上限（内存泄漏判据）。"""
    with SoakGuard(probe=lambda: _ok(1, rss=2000.0), alive=lambda: True, interval_s=1.0,
                   status_path=tmp_path / "s.json", max_rss_mb=1500) as g:
        assert _wait(g)
        assert g.abort_reason == "rss_ceiling_exceeded"

    script = [_ok(1, rss=400.0), _ok(2, rss=600.0)]
    probe, _ = _make_probe(script)
    with SoakGuard(probe=probe, alive=lambda: True, interval_s=1.0,
                   status_path=tmp_path / "s2.json", max_rss_growth_pct=25.0) as g:
        assert _wait(g), "RSS 增长 50% 未被哨兵发现"
        assert g.abort_reason == "rss_growth_exceeded"


def test_transient_http_blip_does_not_abort(tmp_path):
    """单次 HTTP 抖动不误杀：连续 3 次才判失败。"""
    script = [_ok(1), {"http_ok": False}, _ok(2), _ok(3), _ok(4)]
    probe, _ = _make_probe(script)
    with SoakGuard(probe=probe, alive=lambda: True, interval_s=1.0,
                   status_path=tmp_path / "s.json", max_consecutive_failures=3) as g:
        time.sleep(3.5)
        assert not g.should_abort(), g.snapshot()
        assert g.consecutive_failures == 0  # 抖动后已恢复计数


def test_consecutive_failures_abort(tmp_path):
    """连续软失败达上限即停。"""
    with SoakGuard(probe=lambda: {"http_ok": False}, alive=lambda: True, interval_s=1.0,
                   status_path=tmp_path / "s.json", max_consecutive_failures=3) as g:
        assert _wait(g)
        assert g.abort_reason == "consecutive_probe_failures"


def test_p95_exceeded_is_soft_failure(tmp_path):
    """P95 超阈值：连续超才即停（单帧抖动不算）。"""
    # 计数必须递增：否则"停滞"判据会和 P95 判据竞争，导致断言随机（用例自身的坑）
    state = {"c": 0}

    def probe():
        state["c"] += 1
        return _ok(state["c"], p95=5000.0)
    with SoakGuard(probe=probe, alive=lambda: True, interval_s=1.0,
                   status_path=tmp_path / "s.json", max_p95_ms=3000,
                   max_consecutive_failures=2) as g:
        assert _wait(g)
        assert g.abort_reason == "consecutive_probe_failures"
        assert any(w["kind"] == "p95_exceeded" for w in g.snapshot()["warnings"])


def test_http_down_but_pipeline_alive_is_busy_not_dead(tmp_path):
    """HTTP 不通但流水线仍在推进：判'忙'——只告警、给宽限，不在几十秒内误杀。

    24h 实跑教训：周期性清理/备份阻塞事件循环时 HTTP 会失联，但检测仍在写库，
    此时判死会白白终止一次本可恢复的长跑。
    """
    with SoakGuard(probe=lambda: {"http_ok": False}, alive=lambda: True,
                   liveness=lambda: True,  # DB 仍在写入
                   interval_s=1.0, status_path=tmp_path / "s.json",
                   max_consecutive_failures=3, max_busy_failures=10) as g:
        time.sleep(3.5)
        assert not g.should_abort(), g.snapshot()   # 3 次软失败不够（旧逻辑此时已误停）
        assert g.busy_failures >= 2 and g.consecutive_failures == 0
        assert any(w["kind"] == "http_unreachable_but_pipeline_alive" for w in g.snapshot()["warnings"])


def test_persistent_unresponsive_aborts_as_unresponsive(tmp_path):
    """但'忙'不是无限期：持续失联到 max_busy_failures 仍判失败（API 不可用即为故障）。"""
    with SoakGuard(probe=lambda: {"http_ok": False}, alive=lambda: True,
                   liveness=lambda: True, interval_s=1.0,
                   status_path=tmp_path / "s.json", max_busy_failures=3) as g:
        assert _wait(g), "持续失联未被判失败"
        assert g.abort_reason == "unresponsive_too_long"


def test_start_overwrites_stale_status_file(tmp_path):
    """启动即重写状态文件：上一轮的 aborted=True 绝不能被外部巡检误读成本轮状态。"""
    status = tmp_path / "s.json"
    status.write_text(json.dumps({"aborted": True, "abort_reason": "server_process_exited"}), encoding="utf-8")
    with SoakGuard(probe=lambda: _ok(1), alive=lambda: True, interval_s=1.0,
                   status_path=status) as g:
        snap = json.loads(status.read_text(encoding="utf-8"))
        assert snap["aborted"] is False and snap["abort_reason"] is None
        assert snap["run_id"]  # 带运行标识，便于区分不同轮次
        assert g._run_id == snap["run_id"]


def test_probe_gap_detects_host_stall(tmp_path):
    """心跳出现远超预期的大间隔（主机休眠/系统停顿）：显式记录，数据可信度可追溯。"""
    with SoakGuard(probe=lambda: _ok(1), alive=lambda: True, interval_s=1.0,
                   status_path=tmp_path / "s.json") as g:
        time.sleep(2.2)
        # 模拟一次 120s 的停顿（主机休眠后线程恢复执行）
        g._last_mono = time.monotonic() - 120.0
        g._tick()
        assert any(w["kind"] == "probe_gap_suspected_host_stall" for w in g.snapshot()["warnings"])
        assert g.max_probe_gap_s >= 120.0


def test_first_abort_reason_is_preserved(tmp_path):
    """多故障并发时保留首因，现场不被后续覆盖。"""
    with SoakGuard(probe=lambda: {"http_ok": False}, alive=lambda: False, interval_s=1.0,
                   status_path=tmp_path / "s.json") as g:
        assert _wait(g)
        assert g.abort_reason == "server_process_exited"  # 硬失败优先于软失败
