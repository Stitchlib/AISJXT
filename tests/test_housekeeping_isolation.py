"""启动期/周期性治理任务的隔离性回归测试。

背景（24h 实跑真实事故）：后台治理线程删除文件时被外部删除保护拦截，抛 SystemExit；
该 SystemExit 逃逸到 asyncio Task 后，被 asyncio 默认异常处理器转成"停止整个事件循环"，
**一次清理失败直接掀翻整台 API 服务**（进程消失，压测 90 秒内被哨兵判死）。

治理任务不是主链路：任何失败都只能记录，绝不允许影响服务可用性。
"""
from __future__ import annotations

import asyncio

import pytest

from main import _backup_work, _guard_housekeeping, _retention_work, _startup_housekeeping


def _boom() -> None:
    raise SystemExit(1)


def test_guard_swallows_systemexit():
    """吞掉 SystemExit，返回 None，不让它逃逸到事件循环。"""
    assert _guard_housekeeping("单元测试", _boom) is None


def test_guard_swallows_ordinary_exception():
    def _err():
        raise RuntimeError("磁盘不可写")

    assert _guard_housekeeping("单元测试", _err) is None


def test_guard_passes_through_value():
    assert _guard_housekeeping("单元测试", lambda: 42) == 42


def test_systemexit_in_housekeeping_does_not_kill_event_loop():
    """回归核心：治理任务抛 SystemExit 后，事件循环必须还活着。

    未加固时，asyncio.run 会抛 RuntimeError("Event loop stopped before Future completed")。
    """
    async def main() -> bool:
        task = asyncio.create_task(asyncio.to_thread(_guard_housekeeping, "治理", _boom))
        await asyncio.sleep(0.2)
        return task.done()

    assert asyncio.run(main()) is True


def test_startup_housekeeping_survives_all_failures():
    """三步治理全炸也不能抛出：清理/备份失败只记录不致命。"""

    class _Boom:
        def cleanup_retention(self, days):
            raise SystemExit(1)

        def cleanup_images(self):
            raise SystemExit(1)

        def backup(self, dir_=None):
            raise SystemExit(1)

        def prune_backups(self, n, dir_=None):
            raise SystemExit(1)

    class _Engine:
        def cleanup_images(self):
            raise SystemExit(1)

    class _Cm:
        def get(self):
            return type("C", (), {
                "data_retention_days": 180,
                "image_retention_days": 90,
                "image_quota_gb": 10.0,
                "backup_retention": 7,
                "backup_dir": None,
            })()

    out = _startup_housekeeping(_Boom(), _Cm(), _Engine())
    assert out["rows_removed"] == 0 and out["removed_images"] == 0 and out["backup"] is None


def test_periodic_work_survives_failures():
    """周期性清理/备份同样不许抛：失败返回零值，循环继续下一轮。"""
    class _BoomDb:
        def cleanup_retention(self, days):
            raise SystemExit(1)

        def backup(self, dir_=None):
            raise SystemExit(1)

        def prune_backups(self, n, dir_=None):
            raise SystemExit(1)

    class _Cm:
        def get(self):
            return type("C", (), {"data_retention_days": 180, "backup_retention": 7, "backup_dir": None})()

    res = _retention_work(_BoomDb(), _Cm(), None)
    assert res["rows_removed"] == 0
    res2 = _backup_work(_BoomDb(), _Cm())
    assert res2["path"] is None and res2["removed"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
