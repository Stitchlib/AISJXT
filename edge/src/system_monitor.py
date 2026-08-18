"""系统资源监控：CPU/内存/磁盘采集与健康分级。

无 psutil 时优雅降级（返回 0 值并标记 psutil_available=False），
保证系统在最小化环境下仍可运行与测试。
"""
from __future__ import annotations

from datetime import datetime

try:
    import psutil
    _HAS_PSUTIL = True
except Exception:  # pragma: no cover - 依赖缺失场景
    _HAS_PSUTIL = False


def get_system_health() -> dict:
    if _HAS_PSUTIL:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
    else:  # pragma: no cover
        cpu = mem = disk = 0.0

    if cpu > 90 or mem > 90 or disk > 90:
        status = "critical"
    elif cpu > 70 or mem > 70 or disk > 85:
        status = "warning"
    else:
        status = "healthy"

    return {
        "timestamp": datetime.now().isoformat(),
        "cpu_percent": round(cpu, 1),
        "memory_percent": round(mem, 1),
        "disk_percent": round(disk, 1),
        "status": status,
        "psutil_available": _HAS_PSUTIL,
    }
