"""真实摄像头浸泡测试（G8 预验证 / 24h 实跑入口）。

用法：
    python tests/performance/real_camera_soak.py --duration 600 --cameras cam_net_192_168_1_4,cam_001 --port 8018

流程：
1. 以子进程启动真实 uvicorn 服务（生产配置 data/inspection.db，非 TestClient）；
2. 登录 → 启动指定摄像头检测（真实 RTSP + 仿真摄混跑，验证 G5 并发与共享推理）；
3. 周期采样：检测计数、HTTP 状态、服务进程 RSS、DB 尺寸；
4. 结束后停止检测、输出 JSON 摘要（可归档 docs/stability/）。

判定：无服务崩溃、检测计数持续增长、RSS 波动 < 20%。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EDGE = ROOT / "edge"
DB_PATH = ROOT / "data" / "inspection.db"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from soak_guard import SoakGuard  # noqa: E402  长跑哨兵（心跳探测 + 即停告警）


def _http(method: str, url: str, token: str | None = None, payload: dict | None = None, timeout: float = 10.0):
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if payload is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(payload).encode()
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def _db_size_mb() -> float:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            total += p.stat().st_size
    return round(total / 1024 / 1024, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=600, help="浸泡时长（秒）")
    ap.add_argument("--cameras", type=str, default="cam_net_192_168_1_4,cam_001")
    ap.add_argument("--port", type=int, default=8018)
    ap.add_argument("--sample-interval", type=int, default=30)
    ap.add_argument("--report-dir", type=str, default="docs/stability")
    # ---- 哨兵（SoakGuard）：主动故障发现，不等跑完才知道 ----
    ap.add_argument("--heartbeat", type=int, default=30, help="哨兵心跳探测间隔（秒）")
    ap.add_argument("--status-file", type=str, default="docs/stability/soak_status.json",
                    help="哨兵实时状态文件（原子写，可随时查看）")
    ap.add_argument("--max-rss-mb", type=float, default=1500, help="RSS 绝对上限（MB），超过即停")
    ap.add_argument("--max-rss-growth-pct", type=float, default=25, help="RSS 相对基线增长上限（%%），超过即停")
    ap.add_argument("--max-p95-ms", type=float, default=3000, help="单帧处理 P95 上限（ms）")
    ap.add_argument("--max-stall", type=int, default=3,
                    help="检测计数连续停滞的心跳次数上限（引擎卡死/摄像头掉线判据）")
    ap.add_argument("--max-failures", type=int, default=3, help="连续软失败心跳次数上限（流水线停滞时）")
    ap.add_argument("--max-busy", type=int, default=10,
                    help="HTTP 失联但流水线仍在推进时的宽限心跳数（事件循环阻塞属'忙'非'死'，超此值才判失败）")
    ap.add_argument("--alert-webhook", type=str, default="", help="即停时告警 webhook（generic 格式）")
    ap.add_argument("--ready-timeout", type=int, default=900,
                    help="服务就绪等待上限（秒）——模型加载+后台治理可能耗时数分钟，别把启动慢误判成挂了")
    args = ap.parse_args()

    base = f"http://127.0.0.1:{args.port}/api/v1"
    # 报告路径前置：增量落盘——24h 长跑即使进程被杀，已采样数据也不会丢失
    report_dir = ROOT / args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"real_camera_soak_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"

    def _flush_report(partial: bool = True, extra: dict | None = None):
        doc = {
            "partial": partial,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": {
                "duration_s": args.duration,
                "cameras": args.cameras.split(","),
                "sample_interval_s": args.sample_interval,
                "server": f"uvicorn :{args.port} (生产配置 data/inspection.db)",
            },
            "samples": samples,
            "guard": guard_snapshot,  # 哨兵实时健康度（心跳/停滞/告警计数/即停原因）
        }
        if extra:
            doc.update(extra)
        report_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return doc

    guard_snapshot: dict = {}  # 占位：哨兵创建后持续更新，随增量报告落盘
    # 服务端日志必须落盘：进程崩溃/异常栈是事后定位的唯一线索（原先丢弃到 DEVNULL，
    # 24h 实跑出问题时完全无法回溯）。
    server_log = report_dir / f"server_{datetime.now().strftime('%Y%m%dT%H%M%S')}.log"
    server_log_fh = open(server_log, "w", encoding="utf-8", errors="replace")
    print(f"SERVER_LOG {server_log}", flush=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=str(EDGE),
        stdout=server_log_fh,
        stderr=subprocess.STDOUT,
    )
    samples: list[dict] = []
    summary: dict = {"pass": False}
    try:
        import psutil

        srv = psutil.Process(proc.pid)
    except ImportError:
        srv = None

    try:
        # 等服务就绪（RTSP 摄像头打开在检测启动后进行，不影响 API 就绪）。
        # 注意：模型加载 + 后台治理会让启动耗时随数据量增长到数分钟，等待窗口必须足够长，
        # 否则会把"启动慢"误判成"服务挂了"（实测 1.5 万张图片时启动约 6 分钟）。
        ready = False
        t_ready = time.time()
        next_progress = 30.0
        while time.time() - t_ready < args.ready_timeout:
            if proc.poll() is not None:
                print("SERVER_DIED_EARLY", flush=True)
                return 2
            code, _ = _http("GET", f"{base}/../docs")
            code2, _ = _http("POST", f"{base}/auth/login", payload={"username": "admin", "password": "admin123"})
            if code2 == 200:
                ready = True
                break
            waited = time.time() - t_ready
            if waited >= next_progress:
                print(f"[WAIT] 服务尚未就绪，已等待 {waited:.0f}s（上限 {args.ready_timeout}s）", flush=True)
                next_progress += 30.0
            time.sleep(2)
        if not ready:
            print(f"SERVER_NOT_READY (timeout={args.ready_timeout}s)", flush=True)
            return 2
        print(f"READY in {time.time() - t_ready:.0f}s", flush=True)
        _code, body = _http("POST", f"{base}/auth/login", payload={"username": "admin", "password": "admin123"})
        token = body.get("access_token") or body.get("token")
        h = token

        def _authed_get(path: str) -> tuple[int, dict]:
            """GET with auto re-login on 401（token_expire_minutes 默认 12h，24h 长跑必须续期）。"""
            nonlocal token
            code, body = _http("GET", f"{base}{path}", token=token)
            if code == 401:
                _c, b = _http("POST", f"{base}/auth/login", payload={"username": "admin", "password": "admin123"})
                if _c == 200:
                    token = b.get("access_token") or b.get("token")
                    code, body = _http("GET", f"{base}{path}", token=token)
            return code, body

        # 启动检测（G5 多摄并发；真实 RTSP 首次打开可能需 30s+ 握手）
        t0 = time.time()
        code, body = _http(
            "POST",
            f"{base}/inspection/start?camera_id={args.cameras.replace(',', '%2C')}",
            token=h,
        )
        if code != 200:
            summary["error"] = f"start failed: {code} {body}"
            print(json.dumps(summary, ensure_ascii=False))
            return 3
        print(f"STARTED cameras={args.cameras} at {datetime.now().isoformat(timespec='seconds')}", flush=True)
        if srv:
            try:
                print(f"SERVER_RSS_MB={(srv.memory_info().rss + sum(c.memory_info().rss for c in srv.children(recursive=True))) / 1024 / 1024:.1f}", flush=True)
            except Exception:
                pass

        def _rss_mb():
            if not srv:
                return None
            try:
                # 服务 RSS = 主进程 + 全部子进程（兜底 reload/worker 场景）
                return (srv.memory_info().rss + sum(c.memory_info().rss for c in srv.children(recursive=True))) / 1024 / 1024
            except Exception:
                return None

        def _probe() -> dict:
            """哨兵探针：HTTP 状态 + 延迟/错误码 + RSS（token 自动续期）。"""
            t = time.time()
            code, st = _authed_get("/inspection/status")
            http_ms = round((time.time() - t) * 1000, 1)
            return {
                "http_ok": code == 200,
                "http_code": code,
                "http_ms": http_ms,
                "error": (st or {}).get("error") if isinstance(st, dict) else None,
                "total_processed": st.get("total_processed"),
                "running_cameras": [c.get("camera_id") for c in (st.get("running_cameras") or [])],
                "rss_mb": round(_rss_mb(), 1) if _rss_mb() else None,
                "p95_ms": (st.get("last_result") or {}).get("processing_time_ms"),
            }

        _db_mtime = {"v": max(
            (Path(str(DB_PATH) + s).stat().st_mtime for s in ("", "-wal") if Path(str(DB_PATH) + s).exists()),
            default=0.0,
        )}

        def _pipeline_alive() -> bool:
            """第二存活信号：DB/WAL 仍在被写入 = 流水线还在干活（HTTP 不通 ≠ 服务死了）。"""
            m = max(
                (Path(str(DB_PATH) + s).stat().st_mtime for s in ("", "-wal") if Path(str(DB_PATH) + s).exists()),
                default=0.0,
            )
            advanced = m > _db_mtime["v"]
            _db_mtime["v"] = max(m, _db_mtime["v"])
            return advanced

        guard = SoakGuard(
            probe=_probe,
            alive=lambda: proc.poll() is None,
            liveness=_pipeline_alive,
            interval_s=args.heartbeat,
            status_path=ROOT / args.status_file,
            max_rss_mb=args.max_rss_mb,
            max_rss_growth_pct=args.max_rss_growth_pct,
            max_p95_ms=args.max_p95_ms,
            max_stall_probes=args.max_stall,
            max_consecutive_failures=args.max_failures,
            max_busy_failures=args.max_busy,
            webhook_url=args.alert_webhook,
        ).start()
        print(f"GUARD heartbeat={args.heartbeat}s status={args.status_file}", flush=True)

        first_count = None
        while time.time() - t0 < args.duration:
            if guard.should_abort():
                break
            # 分片睡眠：即停信号到达后 5s 内响应，而不是等一个完整采样间隔
            for _ in range(max(1, args.sample_interval // 5)):
                time.sleep(5)
                if guard.should_abort():
                    break
            if guard.should_abort():
                break
            elapsed = round(time.time() - t0, 1)
            code, st = _authed_get("/inspection/status")
            rss = _rss_mb()
            sample = {
                "elapsed_s": elapsed,
                "http_ok": code == 200,
                "total_processed": st.get("total_processed"),
                "running_cameras": [c.get("camera_id") for c in st.get("running_cameras", [])],
                "rss_mb": round(rss, 1) if rss else None,
                "db_mb": _db_size_mb(),
                "p95_ms": ((st.get("last_result") or {}).get("processing_time_ms")),
            }
            samples.append(sample)
            print(json.dumps(sample, ensure_ascii=False), flush=True)
            guard_snapshot.update(guard.snapshot())
            _flush_report(partial=True)  # 增量落盘，防长跑中断丢数据
            if first_count is None and sample["total_processed"]:
                first_count = sample["total_processed"]

        # 停止检测（用当前有效 token，24h 后过期引用早已失效）
        _http("POST", f"{base}/inspection/stop", token=token)
        time.sleep(2)

        guard.stop()
        guard_snapshot.update(guard.snapshot())
        aborted_reason = guard.abort_reason

        counts = [s["total_processed"] or 0 for s in samples]
        rss_values = [s["rss_mb"] for s in samples if s["rss_mb"]]
        growth = (max(rss_values) - min(rss_values)) / min(rss_values) * 100 if rss_values else None
        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": {
                "duration_s": args.duration,
                "cameras": args.cameras.split(","),
                "sample_interval_s": args.sample_interval,
                "server": f"uvicorn :{args.port} (生产配置 data/inspection.db)",
            },
            "results": {
                "server_alive": proc.poll() is None,
                "samples": len(samples),
                "http_all_ok": all(s["http_ok"] for s in samples),
                "total_processed_final": counts[-1] if counts else 0,
                "count_monotonic_growing": counts[-1] > counts[0] if len(counts) > 1 else False,
                "rss_min_mb": min(rss_values) if rss_values else None,
                "rss_max_mb": max(rss_values) if rss_values else None,
                "rss_growth_pct": round(growth, 2) if growth is not None else None,
                "db_final_mb": samples[-1]["db_mb"] if samples else None,
                "expected_duration_s": args.duration,
                "actual_duration_s": round(time.time() - t0, 1),
            },
            "guard": dict(guard_snapshot, aborted=bool(aborted_reason), abort_reason=aborted_reason),
            "samples": samples,
            "pass": bool(
                samples
                and not aborted_reason
                and all(s["http_ok"] for s in samples)
                and counts[-1] > counts[0]
                and (growth is None or growth < 20.0)
            ),
        }
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
        try:
            server_log_fh.close()
        except Exception:
            pass
        # 最终归档（partial=False 表示跑完正常收尾；被中断则保留最后一次增量）
        summary = _flush_report(partial=False, extra={"results": summary, "pass": summary.get("pass", False)})
        print(f"REPORT {report_path}", flush=True)
        print("PASS" if summary.get("pass") else "FAIL", flush=True)
    return 0 if summary.get("pass") else 1


if __name__ == "__main__":
    sys.exit(main())
