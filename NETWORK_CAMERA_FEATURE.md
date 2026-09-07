# 网络摄像头管理功能

> 本文件是网络摄像头相关功能的**唯一权威文档**。原先散落的
> `QUICK_START_NETWORK_CAMERA.md` 与 `START_NETWORK_CAMERA.md` 已合并至此，
> 仅保留指向本文件的简短入口，避免信息重复与端口/脚本引用失真。

AI 视觉质检系统支持接入真实 RTSP/IP 网络摄像头，与原有的仿真摄像头并存。
后端通过轻量级端口探测发现同网段设备，也可手动添加；前端提供「网络摄像头管理」页面，
支持一键扫描、添加、测试连接与状态监控。

---

## 1. 后端实现

### 核心组件
- **`edge/src/camera_manager.py`** — `CameraManager`
  - `scan_network(subnet, ports=...)`：扫描 IP 范围内的 RTSP/IP 摄像头（探测常见端口 80/554/8000/8554）。
  - `discover_and_add(subnet, username, password, set_active)`：扫描网段并自动注册可用设备。
- **`edge/src/routers/cameras.py`** — REST 端点（前缀 `/api/v1/cameras`）。
- **`edge/src/config_manager.py`** — 摄像头配置持久化到 `edge/config/config.json`。

> 注：历史文档中提到的 `edge/src/api_server.py`、`edge/src/network_camera_scanner.py`
> 等文件名与当前代码结构不符，实际实现见上述文件，请勿照旧文档路径查找。

### API 端点（真实可用）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/v1/cameras` | 获取摄像头列表（含在线/离线状态） | ✅ |
| GET | `/api/v1/cameras/{id}` | 获取单个摄像头 | ✅ |
| GET | `/api/v1/cameras/network/scan?subnet=192.168.1` | 扫描网段（**GET + 查询参数 `subnet`**，非 POST body） | ✅ |
| POST | `/api/v1/cameras` | 添加摄像头（body 见下） | ✅ |
| POST | `/api/v1/cameras/test` | 测试来源是否可连接并取到帧 | ✅ |
| POST | `/api/v1/cameras/discover` | 扫描网段并自动注册 | ✅ |
| PUT | `/api/v1/cameras/{id}` | 更新摄像头（含来源/凭据/类型归一化） | ✅ |
| PUT | `/api/v1/cameras/{id}/active` | 设为当前激活摄像头 | ✅ |
| DELETE | `/api/v1/cameras/{id}` | 删除摄像头 | ✅ |

> ⚠️ 旧的 `POST /cameras/network/scan`、`GET /cameras/network/scan-results`、
> `POST /cameras/network/add`、`POST /cameras/network/test` 端点**不存在**，
> 请勿再调用；扫描结果直接由 `GET /cameras/network/scan` 返回。

### 添加摄像头请求体（POST /api/v1/cameras）

```json
{
  "id": "camera_003",
  "name": "门口摄像头",
  "source": "rtsp://192.168.1.100:554/stream1",
  "type": "rtsp",
  "resolution": {"width": 1920, "height": 1080},
  "fps": 30
}
```

- `type` 省略时按 `source` 自动推断（`rtsp://` → `rtsp`，数字 → `usb`，`http://` → `http`）。
- 若提供 `username` / `password` 且为 `rtsp`/`http` 源，凭据会自动注入 `source`，
  确保取流可用（如 `rtsp://user:pass@ip:port/stream`）。

---

## 2. 前端实现

- **路由**：`frontend/src/router/index.js` 中 `/network-cameras` → `NetworkCameraManager`。
- **主界面**：`frontend/src/views/NetworkCameraManager.vue`
  - 一键扫描、查看结果（IP / 端口 / RTSP 地址）、添加、测试连接、移除、状态监控。
- **入口**：`frontend/src/views/DeviceManagement.vue` 的「网络摄像头」按钮跳转。
- **API 封装**：`frontend/src/api/index.js` 的 `networkCameraApi`。

### 访问地址
- **本地开发**：`http://localhost:3000/network-cameras`
  （前端 dev server 端口见 `vite.config.js` 的 `server.port`，当前为 **3000**，
  旧文档写的 3001 / 5173 均已失效）。
- **Docker 一键部署**：`http://localhost/network-cameras`（前端由 Nginx 在 80 端口托管）。

---

## 3. 支持的摄像头品牌（RTSP 格式）

| 品牌 | 默认端口 | URL 格式示例 |
|------|---------|--------------|
| 海康威视 | 554 | `rtsp://ip:554/h264/ch1/main/av_stream` |
| 大华 | 554 | `rtsp://ip:554/cam/realmonitor?channel=1&subtype=0` |
| Axis | 554 | `rtsp://ip:554/live/ch1` |
| 华为 | 554 | `rtsp://ip:554/streaming/channels/101` |
| 通用 | 554 / 8554 | `rtsp://ip:554/stream1` |

---

## 4. 使用方法

### 方法一：Web 界面（推荐）
1. 访问 `http://localhost:3000/network-cameras`（本地）或 `http://localhost/network-cameras`（Docker）。
2. 点击「扫描网络摄像头」，输入 IP 范围（如 `192.168.1.1-192.168.1.255`）。
3. 选择扫描结果中的设备，填写 ID / 名称后添加。
4. 点击「测试连接」验证可用性（绿=在线，红=故障）。

### 方法二：API 调用（curl）

```bash
# 1. 扫描网段（GET + subnet 查询参数）
curl "http://localhost:8000/api/v1/cameras/network/scan?subnet=192.168.1"

# 2. 添加摄像头
curl -X POST "http://localhost:8000/api/v1/cameras" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "camera_003",
    "name": "门口摄像头",
    "source": "rtsp://192.168.1.100:554/stream1",
    "type": "rtsp",
    "resolution": {"width": 1920, "height": 1080},
    "fps": 30
  }'

# 3. 测试连接（可带凭据）
curl -X POST "http://localhost:8000/api/v1/cameras/test" \
  -H "Content-Type: application/json" \
  -d '{"source": "rtsp://admin:password@192.168.1.100:554/stream1"}'

# 4. 自动发现并注册
curl -X POST "http://localhost:8000/api/v1/cameras/discover" \
  -H "Content-Type: application/json" \
  -d '{"subnet": "192.168.1", "username": "admin", "password": "56789-abc", "set_active": true}'
```

> 所有写操作（添加/测试/发现）需携带 `Authorization: Bearer <token>` 请求头。

---

## 5. 配置说明

摄像头配置持久化于 **`edge/config/config.json`**（旧文档提到的 `config.yaml` 不存在）。
相关字段：`cameras[]`、`active_camera_id`、`auto_discover`、`discover_username`、
`discover_password`。新增/修改摄像头会即时写回该文件。

---

## 6. 故障排查

### 问题 1：扫描不到摄像头
- 确认摄像头已通电联网，且与运行后端的主机在**同一网段**；
- 确认 IP 范围正确（本机网段可用 `ipconfig` / `ifconfig` 查看）；
- 防火墙可能拦截扫描端口，可临时关闭测试；
- 网络较差时增大超时（扫描超时在 `camera_manager.scan_network` 中设定）。

### 问题 2：无法连接 RTSP 流
- 用 **VLC 播放器**先验证 RTSP 地址是否可达；
- 需要认证时，地址中带上账号密码：`rtsp://user:pass@ip:port/stream`；
- 端口被防火墙阻止时调整网络策略。

### 问题 3：页面打不开
- 本地开发确认前端已启动：`cd frontend && npm run dev`（监听 3000）；
- 清除浏览器缓存后重试（Ctrl+F5 硬刷新）。

---

## 7. 性能与安全建议

- **扫描优化**：先小范围（如 `.1-.50`）确认可行再扩大；避开网络高峰；视网络质量调整超时。
- **运行优化**：建议同时运行的摄像头不超过 8 个；优先子码流（720p）；25–30 FPS 足够多数场景。
- **安全**：
  1. 所有摄像头必须修改出厂默认密码；
  2. RTSP 流应配置用户名/密码认证；
  3. 摄像头建议置于独立 VLAN 网络隔离；
  4. 及时升级摄像头固件。

---

## 8. 后续计划

- [ ] 支持 ONVIF 协议自动发现
- [ ] 支持批量添加 / 导入
- [ ] 增加摄像头预览功能
- [ ] 支持更多品牌与 URL 格式
- [ ] 摄像头分组管理
