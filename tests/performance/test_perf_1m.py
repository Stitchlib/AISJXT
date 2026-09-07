"""百万级数据性能验收（M2 验收门槛）：

独立模块级 fixture 将应用配置/数据库重定向到专属临时库，灌入 100 万行检测记录，
随后测量生产验收口径的关键延迟：
- 分页查询（page）            < 100ms
- 报表聚合（summary/shares/trend） < 500ms
- CSV 导出文件体积            < 200MB（流式写出，不把全表载入内存）

行数可通过环境变量 AIQC_PERF_ROWS 覆盖（默认 1_000_000），便于快速冒烟。
该测试与常规单元/集成测试隔离运行，避免百万行数据污染共享临时库。
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

EDGE = Path(__file__).resolve().parent.parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))

import src.config_manager as cm_mod  # noqa: E402
from main import app  # noqa: E402

N = int(os.environ.get("AIQC_PERF_ROWS", "1000000"))
PAGE_THRESHOLD = 0.10        # 100ms
REPORT_THRESHOLD = 0.50      # 500ms
CSV_MAX_BYTES = 200 * 1024 * 1024  # 200MB


def _seed(db, n: int) -> None:
    """直接用底层连接 executemany 灌数据（单事务），避免逐行 Python 开销。"""
    cameras = [f"cam_{i:03d}" for i in range(1, 9)]
    rows = []
    for i in range(n):
        cam = cameras[i % len(cameras)]
        day = ((i // 1000) % 25) + 1
        hour = i % 24
        minute = (i * 7) % 60
        ts = f"2026-08-{day:02d}T{hour:02d}:{minute:02d}:00+00:00"
        dc = i % 5                      # 缺陷数 0-4
        tc = 10
        dr = round(dc / tc, 4)
        if dc:
            defects = json.dumps([{"class_name": f"defect_{i % 7}", "confidence": 0.9}] * dc)
        else:
            defects = "[]"
        rows.append((ts, cam, "", defects, tc, dc, dr, 12.5, 0, 2))
    with db._conn_cm() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executemany(
            "INSERT INTO detection_results "
            "(timestamp, camera_id, image_path, defects, total_count, "
            "defect_count, defect_rate, processing_time_ms, is_simulation, metric_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()


@pytest.fixture(scope="module")
def seeded_client():
    import fastapi.testclient  # local import to keep top clean

    tmp = Path(tempfile.mkdtemp(prefix="aiqc_perf_"))
    cfg = tmp / "config" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    dbp = str(tmp / "inspection.db")
    orig = EDGE / "config" / "config.json"
    data = json.loads(orig.read_text(encoding="utf-8")) if orig.exists() else {}
    data["db_path"] = dbp
    cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 重定向配置解析到专属临时库，并灌入百万行
    cm_mod.ConfigManager._resolve_path = staticmethod(lambda: str(cfg))
    from src.database import Database

    db = Database(dbp)
    _seed(db, N)
    # 直接 SQL 灌库绕过了增量计数，需全量重算补齐聚合计数器（一次性开销）
    db.recompute_aggregates()
    total = db.get_statistics().get("total", N)
    print(f"\n[perf] seeded {total} rows")

    with fastapi.testclient.TestClient(app) as c:
        yield c


def _median_latency(fn, warmup=1, repeat=3):
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    return samples[len(samples) // 2]


def test_page_query_latency(seeded_client):
    db = seeded_client.app.state.db
    dt = _median_latency(lambda: db.query_results(page=1, page_size=50))
    print(f"\n[perf] page query (page=1,size=50) median = {dt*1000:.1f} ms")
    assert dt < PAGE_THRESHOLD


def test_report_summary_latency(seeded_client):
    db = seeded_client.app.state.db
    dt = _median_latency(lambda: (db.get_statistics(), db.get_type_shares(), db.get_trend()))
    print(f"\n[perf] report aggregation (summary+shares+trend) median = {dt*1000:.1f} ms")
    assert dt < REPORT_THRESHOLD


def test_statistics_individual_latency(seeded_client):
    db = seeded_client.app.state.db
    for name, fn in (
        ("statistics", db.get_statistics),
        ("type_shares", db.get_type_shares),
        ("trend", db.get_trend),
    ):
        dt = _median_latency(fn)
        print(f"\n[perf] {name} median = {dt*1000:.1f} ms")
        assert dt < REPORT_THRESHOLD


def test_csv_export_size_and_streaming(seeded_client, tmp_path):
    db = seeded_client.app.state.db
    out = tmp_path / "export_1m.csv"
    t0 = time.perf_counter()
    path = db.export_csv(str(out))
    dt = time.perf_counter() - t0
    size = Path(path).stat().st_size
    print(f"\n[perf] CSV export elapsed = {dt:.1f}s, size = {size/1024/1024:.1f} MB")
    assert size < CSV_MAX_BYTES
    assert size > 0
