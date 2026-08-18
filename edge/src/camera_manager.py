"""摄像头管理：设备生命周期、状态与网络发现。

职责边界：
- 维护摄像头清单（来自配置）
- 维护在线/离线状态
- 提供轻量级网络扫描接口（真实 ONVIF/RTSP 发现在此扩展）

注意：当前不强制依赖 OpenCV；真实摄像头接入在 connect() 中按需加载，
避免无摄像头环境（如 CI）下导入失败。
"""
from __future__ import annotations

import logging
import socket
import threading
from typing import Dict, List

from .config_manager import CameraConfig, ConfigManager
from .models import CameraInfo, CameraType, normalize_camera_type

logger = logging.getLogger("camera_manager")


class CameraManager:
    def __init__(self) -> None:
        self._cm = ConfigManager()
        self._lock = threading.Lock()
        self._cameras: Dict[str, CameraInfo] = {}
        self._load_from_config()

    def _load_from_config(self) -> None:
        """从配置装载摄像头清单。

        类型一律经 normalize_camera_type 归一化：历史配置里可能存在 "simulation"、
        "rtsp" 等非枚举写法，若直接 CameraType(c.type) 会在启动时抛异常导致整个
        后端起不来。归一化让脏数据退化为仿真而不是崩溃。
        """
        for c in self._cm.get().cameras:
            try:
                self._cameras[c.id] = CameraInfo(
                    id=c.id,
                    name=c.name,
                    type=CameraType(normalize_camera_type(c.type)),
                    source=c.source,
                    enabled=c.enabled,
                    status=getattr(c, "status", "unknown") or "unknown",
                )
            except Exception as e:  # 单个摄像头配置异常不应阻塞其余设备装载
                logger.warning("摄像头配置 %s 装载失败，已跳过: %s", getattr(c, "id", "?"), e)

    def list(self) -> List[CameraInfo]:
        return list(self._cameras.values())

    def get(self, cam_id: str) -> CameraInfo | None:
        return self._cameras.get(cam_id)

    def add(self, info: CameraInfo) -> None:
        with self._lock:
            self._cameras[info.id] = info

    def remove(self, cam_id: str) -> None:
        with self._lock:
            self._cameras.pop(cam_id, None)

    def update_status(self, cam_id: str, status: str) -> None:
        with self._lock:
            if cam_id in self._cameras:
                self._cameras[cam_id].status = status

    def online_count(self) -> int:
        return sum(1 for c in self._cameras.values() if c.status == "online")

    def scan_network(self, subnet: str = "192.168.1", ports: tuple = (80, 554, 8000, 8554)) -> List[dict]:
        """轻量级端口探测式网络摄像头发现（非阻塞、超时短）。

        生产环境应替换为 ONVIF WS-Discovery / RTSP 探测。
        """
        found: List[dict] = []
        for i in range(1, 255):
            host = f"{subnet}.{i}"
            for port in ports:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(0.15)
                        if s.connect_ex((host, port)) == 0:
                            found.append({"host": host, "port": port})
                            break
                except Exception:
                    continue
        return found

    @staticmethod
    def build_rtsp_candidates(ip: str, username: str | None = None, password: str | None = None) -> List[str]:
        """为某 IP 构造一组常见厂商 RTSP URL（匿名优先，其次带账号）。"""
        auth = f"{username}:{password or ''}@" if username else ""
        paths = [
            "",
            "/stream1",
            "/stream0",
            "/Streaming/Channels/101",  # 海康
            "/h264/ch1/main/av_stream",  # 海康
            "/cam/realmonitor?channel=1&subtype=0",  # 大华
            "/live/ch00_0",  # 天地伟业等
            "/media.amp",  # Axis
            "/axis-media/media.amp",
        ]
        ports = [554, 8554, 8000]
        return [f"rtsp://{auth}{ip}:{p}{path}" for p in ports for path in paths]

    def discover_and_add(
        self,
        subnet: str = "192.168.1",
        username: str | None = None,
        password: str | None = None,
        ports: tuple = (554, 8000, 8554),
        set_active: bool = True,
        probe_timeout: float = 5.0,
        rtsp_only: bool = True,
    ) -> List[CameraInfo]:
        """扫描网段 -> 对每个候选 IP 探测常见 RTSP URL -> 通过验证的自动注册。

        返回本次新注册（或更新）的摄像头列表。已存在的同 IP 摄像头会更新其 source。
        rtsp_only=True 时跳过仅开放 80 端口（纯 Web）的候选，减少无效探测。
        """
        from .camera_capture import probe_source

        found = self.scan_network(subnet, ports)
        if rtsp_only:
            found = [c for c in found if c["port"] in (554, 8000, 8554)]
        added: List[CameraInfo] = []
        for cand in found:
            ip = cand["host"]
            for url in self.build_rtsp_candidates(ip, username, password):
                if probe_source(url, probe_timeout):
                    cam_id = f"cam_net_{ip.replace('.', '_')}"
                    existing = self.get(cam_id)
                    if existing is None:
                        cfg = CameraConfig(
                            id=cam_id, name=f"网络摄像头 {ip}", type="network",
                            source=url, enabled=True,
                            username=username, password=password,
                        )
                        self._cm.add_camera(cfg)
                    else:
                        self._cm.update_camera_source(cam_id, url)
                    info = CameraInfo(
                        id=cam_id, name=f"网络摄像头 {ip}", type=CameraType.NETWORK,
                        source=url, enabled=True, status="online",
                    )
                    self.add(info)
                    added.append(info)
                    if set_active:
                        try:
                            self._cm.set_active_camera(cam_id)
                        except Exception:
                            pass
                    break  # 该 IP 已找到可用流，转下一个
        return added
