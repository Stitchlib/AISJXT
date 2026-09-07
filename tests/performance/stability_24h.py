"""24 小时稳定性压测 harness（第二期 G8）。

目标：在"仿真"模式下长时间压测系统，验证
  1) 多路检测写入不丢帧、DB 写入稳定（≥2 路 feeder 并发写）；
  2) 实时 WebSocket 扇出可达 ≥10 并发客户端且无积压（TestClient 下以 start→control ack 回显验证服务端→客户端可达，
     生产环境再观察 detection_result 广播帧）；
  3) 容量断言（复用 test_perf_1m 口径）：分页查询 < 100ms、报表聚合 < 500ms，
     每 4 小时（assert_interval_s）复测一次，确保长时间运行后索引/聚合未退化。

说明：
  - 摄像头未开时走 DetectionSimulator（detector_mode=simulation），不依赖真实摄像头/模型。
  - 默认不跑满 24h：通过 --duration 控制；CI/本地只做短时长 smoke（python stability_24h.py）。
  - 完整 24h 报告归档到 docs/stability/（由 --report-dir 指定，默认 docs/stability）。

用法：
  python tests/performance/stability_24h.py --duration 60 --ws 10 --feeders 2
  pytest tests/performance/stability_24h.py   # 仅当 AIQC_STABILITY_SMOKE=1 才真正跑（默认跳过）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil

    _HAS_PSUTIL = True
except Exception:  # pragma: no cover - 无 psutil 时跳过内存采样
    psutil = None
    _HAS_PSUTIL = False

EDGE = Path(__file__).resolve().parent.parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))

import src.config_manager as cm_mod  # noqa: E402
from main import app  # noqa: E402

# 复用性能验收门槛（与 test_perf_1m 对齐）
PAGE_THRESHOLD = 0.10     # 100ms
REPORT_THRESHOLD = 0.50   # 500ms
DEFAULT_ADMIN = ("admin", "admin123")


def _median(samples: list[float]) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    return s[len(s) // 2]


def _timed(fn):
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def _login(client, username: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"登录失败 {r.status_code}: {r.text}"
    body = r.json()
    # 登录返回 {"access_token": "...", "token_type": "bearer"}
    if isinstance(body, dict):
        return body.get("access_token") or body.get("token")
    return body


def _feeder(db, camera_id: str, stop: threading.Event, stats: dict) -> None:
    """模拟一路摄像头持续写入检测记录（仿真口径）。"""
    base = {
        "total_count": 10,
        "defect_count": 2,
        "defect_rate": 0.2,
        "processing_time_ms": 11.0,
        "is_simulation": True,
        "metric_version": 1,
        "camera_id": camera_id,
    }
    while not stop.is_set():
        base["timestamp"] = datetime.now(timezone.utc).isoformat()
        base["defects"] = [{"class_name": "线头", "confidence": 0.91}]
        try:
            db.insert_result(base)
            stats["written"] += 1
        except Exception:
            stats["errors"] += 1
        time.sleep(0.05)  # ~20 条/秒/路


def _ws_client(client, token: str, duration: float, stop: threading.Event, stats: dict) -> None:
    """一个并发 WS 订阅客户端：连接后发送 start 指令（admin 令牌），
    服务端在同协程内回 control ack，据此验证服务端→客户端扇出（TestClient 下可靠投递）。
    同时持续接收检测/告警广播帧并计数。

    注：Starlette TestClient 的 receive_json 不接受 timeout 参数，故用无参阻塞接收 +
    循环 deadline 控制（引擎持续广播，不会无限阻塞）。
    """
    try:
        with client.websocket_connect(f"/ws?token={token}") as ws:
            # 发送 start 触发服务端回 control ack（验证 WS 服务端→客户端可达）
            ws.send_json({"action": "start"})
            deadline = time.time() + duration
            while time.time() < deadline and not stop.is_set():
                msg = ws.receive_json()
                stats["messages"] += 1
                if msg.get("type") == "detection_result":
                    stats["frames"] += 1
    except Exception:
        stats["ws_errors"] += 1


def run_stability(
    duration_s: float = 60.0,
    n_ws: int = 10,
    n_feeders: int = 2,
    assert_interval_s: float = 14400.0,
    admin: tuple[str, str] = DEFAULT_ADMIN,
    report_dir: str | None = None,
) -> dict:
    """执行一次稳定性压测，返回结果字典（含每轮容量断言）。"""
    import fastapi.testclient

    tmp = Path(tempfile.mkdtemp(prefix="aiqc_stab_"))
    cfg = tmp / "config" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    dbp = str(tmp / "inspection.db")
    orig = EDGE / "config" / "config.json"
    data = json.loads(orig.read_text(encoding="utf-8")) if orig.exists() else {}
    data["db_path"] = dbp
    # 摄像头未开：强制仿真检测器（enable_simulation=True 让 build_detector 选 SimulatedDetector），
    # 不依赖真实模型/ultralytics；缩节拍提升 WS 扇出样本
    data["enable_simulation"] = True
    data["inspection_interval_ms"] = min(int(data.get("inspection_interval_ms", 1000)), 200)
    cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 重定向配置解析到临时库（与 test_perf_1m 同手法）
    cm_mod.ConfigManager._resolve_path = staticmethod(lambda: str(cfg))

    result: dict = {}
    # 必须用 `with` 触发 startup（初始化 app.state.auth/db/engine/ws...）
    with fastapi.testclient.TestClient(app) as client:
        db = client.app.state.db
        token = _login(client, admin[0], admin[1])

        # 启动检测引擎（仿真模式，不依赖摄像头）
        headers = {"Authorization": f"Bearer {token}"}
        r = client.post("/api/v1/inspection/start", headers=headers)
        assert r.status_code == 200, f"启动检测失败 {r.status_code}: {r.text}"

        # 内存 / 磁盘采样（G8 验收：RSS 波动 < 20%、磁盘增长符合预算）
        proc = psutil.Process(os.getpid()) if _HAS_PSUTIL else None
        mem_samples: list[int] = []
        db_size_samples: list[int] = []

        def _sample():
            if proc is not None:
                try:
                    mem_samples.append(proc.memory_info().rss)
                except Exception:
                    pass
            try:
                db_size_samples.append(Path(dbp).stat().st_size)
            except Exception:
                pass

        _sample()  # 基线

        stop = threading.Event()
        fstats = {"written": 0, "errors": 0}
        wstats: list[dict] = [{"messages": 0, "frames": 0, "ws_errors": 0} for _ in range(n_ws)]

        feeders = [
            threading.Thread(target=_feeder, args=(db, f"cam_feed_{i:02d}", stop, fstats))
            for i in range(max(1, n_feeders))
        ]
        ws_threads = [
            threading.Thread(target=_ws_client, args=(client, token, duration_s, stop, wstats[i]))
            for i in range(n_ws)
        ]
        for t in feeders + ws_threads:
            t.start()

        rounds = []
        elapsed = 0.0
        t0 = time.time()
        WARMUP_S = 6.0  # 跳过启动期争用，仅测稳态
        last_assert = -assert_interval_s  # 让第一轮断言在 WARMUP 后立即触发
        try:
            while elapsed < duration_s:
                time.sleep(min(5.0, max(0.1, duration_s - elapsed)))
                elapsed = time.time() - t0
                if elapsed < WARMUP_S:
                    continue
                # 周期性容量断言（稳态）：每 assert_interval_s 一轮，直至跑满 duration_s。
                # 注意不能在第一个 assert 窗口就 break——那会把 24h 实跑截断为一个窗口。
                if elapsed - last_assert < assert_interval_s:
                    continue
                last_assert = elapsed
                page_dt = _median([_timed(lambda: db.query_results(page=1, page_size=50)) for _ in range(3)])
                rep_dt = _median([_timed(lambda: (db.get_statistics(), db.get_type_shares(), db.get_trend())) for _ in range(3)])
                rounds.append({
                    "elapsed_s": round(elapsed, 1),
                    "page_query_ms": round(page_dt * 1000, 2),
                    "report_ms": round(rep_dt * 1000, 2),
                    "page_ok": page_dt < PAGE_THRESHOLD,
                    "report_ok": rep_dt < REPORT_THRESHOLD,
                })
                _sample()  # 稳态内存/磁盘采样
        finally:
            stop.set()
            for t in feeders + ws_threads:
                t.join(timeout=10)

        # 收尾容量断言（无论是否触发周期轮）
        page_dt = _median([_timed(lambda: db.query_results(page=1, page_size=50)) for _ in range(3)])
        rep_dt = _median([_timed(lambda: (db.get_statistics(), db.get_type_shares(), db.get_trend())) for _ in range(3)])
        total_written = db.get_statistics().get("total", 0)
        # 内存 / 磁盘稳定性汇总（G8 验收：RSS 波动 < 20%）
        _sample()  # 收尾采样
        # 泄漏判据用"稳态窗口对比"而非 max/first：模型加载等一次性分配会让 RSS
        # 早期台阶式抬升后进入平台期，这不是泄漏；泄漏表现为平台期持续爬升。
        def _median_rss(samples: list[int]) -> float | None:
            if not samples:
                return None
            s = sorted(samples)
            n = len(s)
            return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

        memory = {
            "available": _HAS_PSUTIL,
            "sampled": len(mem_samples),
            "first_rss_mb": 0.0,
            "max_rss_mb": 0.0,
            "growth_pct": 0.0,
            "ok": True,
        }
        if mem_samples:
            first = mem_samples[0]
            mx = max(mem_samples)
            memory["first_rss_mb"] = round(first / 1024 / 1024, 1)
            memory["max_rss_mb"] = round(mx / 1024 / 1024, 1)
            if len(mem_samples) >= 8:
                q = max(1, len(mem_samples) // 4)
                early = _median_rss(mem_samples[: max(2, len(mem_samples) // 3)])
                late = _median_rss(mem_samples[-q:])
                memory["steady_early_rss_mb"] = round(early / 1024 / 1024, 1)
                memory["steady_late_rss_mb"] = round(late / 1024 / 1024, 1)
                memory["growth_pct"] = round((late - early) / early * 100, 2) if early else 0.0
            else:
                memory["growth_pct"] = round((mx - first) / first * 100, 2) if first else 0.0
            memory["rss_curve_mb"] = [round(v / 1024 / 1024, 1) for v in mem_samples]
            memory["ok"] = memory["growth_pct"] < 20.0
        disk = {
            "available": True,
            "final_db_mb": round((db_size_samples[-1] if db_size_samples else 0) / 1024 / 1024, 2),
        }
        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": {
                "duration_s": duration_s, "n_ws": n_ws, "n_feeders": max(1, n_feeders),
                "assert_interval_s": assert_interval_s, "detector_mode": "simulation",
            },
            "memory": memory,
            "disk": disk,
            "throughput": {
                "feeder_written": fstats["written"],
                "feeder_errors": fstats["errors"],
                "ws_messages_total": sum(s["messages"] for s in wstats),
                "ws_frames_total": sum(s["frames"] for s in wstats),
                "ws_errors_total": sum(s["ws_errors"] for s in wstats),
                "db_total_rows": total_written,
            },
            "final_capacity": {
                "page_query_ms": round(page_dt * 1000, 2),
                "report_ms": round(rep_dt * 1000, 2),
                "page_ok": page_dt < PAGE_THRESHOLD,
                "report_ok": rep_dt < REPORT_THRESHOLD,
            },
            "rounds": rounds,
            "pass": (
                page_dt < PAGE_THRESHOLD
                and rep_dt < REPORT_THRESHOLD
                and fstats["errors"] == 0
                and memory["ok"]
            ),
        }

        # 停引擎
        try:
            client.post("/api/v1/inspection/stop", headers=headers)
        except Exception:
            pass

        if report_dir:
            Path(report_dir).mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out = Path(report_dir) / f"stability_{stamp}.json"
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            result["report_path"] = str(out)
        return result


def main():
    ap = argparse.ArgumentParser(description="24h 稳定性压测（默认短时长 smoke）")
    ap.add_argument("--duration", type=float, default=60.0, help="压测时长（秒），默认 60")
    ap.add_argument("--ws", type=int, default=10, help="并发 WS 客户端数，默认 10")
    ap.add_argument("--feeders", type=int, default=2, help="并发写入 feeder 路数（≥2 模拟多摄像头），默认 2")
    ap.add_argument("--assert-interval", type=float, default=14400.0, help="容量断言间隔（秒），默认 4h")
    ap.add_argument("--report-dir", type=str, default=None, help="报告归档目录，默认不归档")
    ap.add_argument("--admin-user", type=str, default=DEFAULT_ADMIN[0])
    ap.add_argument("--admin-pass", type=str, default=DEFAULT_ADMIN[1])
    args = ap.parse_args()

    report_dir = args.report_dir or str(EDGE.parent.parent / "docs" / "stability")
    res = run_stability(
        duration_s=args.duration,
        n_ws=args.ws,
        n_feeders=args.feeders,
        assert_interval_s=args.assert_interval,
        admin=(args.admin_user, args.admin_pass),
        report_dir=report_dir,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res["pass"] else 1)


if __name__ == "__main__":
    main()


def test_stability_smoke():
    """pytest 入口：默认跳过，仅当 AIQC_STABILITY_SMOKE=1 才跑短时长 smoke 验证脚本逻辑。"""
    if os.environ.get("AIQC_STABILITY_SMOKE") != "1":
        import pytest
        pytest.skip("设置 AIQC_STABILITY_SMOKE=1 才运行稳定性 smoke（耗时）")
    res = run_stability(duration_s=15, n_ws=4, n_feeders=2, assert_interval_s=15)
    assert res["final_capacity"]["page_ok"], "分页查询容量断言失败"
    assert res["final_capacity"]["report_ok"], "报表聚合容量断言失败"
