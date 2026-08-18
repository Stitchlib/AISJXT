# 网络摄像头管理功能实现总结

## ✅ 已完成功能

### 1. 后端实现

#### 核心组件
- **NetworkCameraScanner** (`edge/src/network_camera_scanner.py`)
  - 支持扫描 IP 范围内的 RTSP/IP 摄像头
  - 自动检测常见端口：554, 8554, 8080, 80
  - 支持多种品牌摄像头 URL 格式
  - 实时测试 RTSP 流可用性

#### API 端点 (`edge/src/api_server.py`)
```
POST   /api/v1/cameras/network/scan         # 扫描网络摄像头
GET    /api/v1/cameras/network/scan-results # 获取扫描结果
POST   /api/v1/cameras/network/add          # 添加摄像头到配置
POST   /api/v1/cameras/network/test         # 测试摄像头连接
```

#### 配置管理
- **ConfigManager.add_camera()** (`edge/src/config_manager.py`)
  - 动态添加摄像头配置
  - 自动保存到 YAML 配置文件
  - 防止 ID 重复

- **CameraManager.get_camera_info()** (`edge/src/camera_manager.py`)
  - 获取所有摄像头信息
  - 返回在线/离线状态
  - 包含分辨率、帧率等参数

### 2. 前端实现

#### 路由配置 (`frontend/src/router/index.js`)
```javascript
{
  path: '/network-cameras',
  name: 'NetworkCameraManager',
  component: NetworkCameraManager,
  meta: { title: '网络摄像头管理' }
}
```

#### 主界面组件 (`frontend/src/views/NetworkCameraManager.vue`)
功能特性：
- ✅ 一键扫描网络摄像头
- ✅ 显示扫描结果（IP、端口、RTSP 地址）
- ✅ 添加摄像头到系统
- ✅ 测试摄像头连接
- ✅ 移除摄像头
- ✅ 实时状态监控

#### 设备管理集成 (`frontend/src/views/DeviceManagement.vue`)
- 新增"网络摄像头"按钮，跳转到专用管理页面
- 支持从设备列表快速访问

#### API 封装 (`frontend/src/api/index.js`)
```javascript
export const networkCameraApi = {
  scanNetworkCameras(),    // 扫描
  getScanResults(),        // 获取结果
  addNetworkCamera(),      // 添加
  testNetworkCamera()      // 测试
}
```

### 3. 支持的摄像头品牌

| 品牌 | URL 格式示例 |
|------|-------------|
| 海康威视 | `rtsp://ip:554/h264/ch1/main/av_stream` |
| 大华 | `rtsp://ip:554/cam/realmonitor?channel=1&subtype=0` |
| Axis | `rtsp://ip:554/live/ch1` |
| 华为 | `rtsp://ip:554/streaming/channels/101` |
| 通用 | `rtsp://ip:554/stream1` |

## 📍 访问路径

### Web 界面
1. **独立页面**: http://localhost:3001/network-cameras
2. **通过设备管理**: http://localhost:3001/devices → 点击"网络摄像头"按钮

### API 端点
基础 URL: `http://localhost:8000/api/v1`

## 🔧 使用方法

### 方法一：Web 界面（推荐）

1. 访问 http://localhost:3001/network-cameras
2. 点击"扫描网络摄像头"
3. 输入 IP 范围（如：`192.168.1.1-192.168.1.255`）
4. 点击"开始扫描"
5. 在扫描结果中选择要添加的摄像头
6. 填写摄像头信息（ID、名称等）
7. 确认添加

### 方法二：API 调用

```bash
# 1. 扫描网络摄像头
curl -X POST "http://localhost:8000/api/v1/cameras/network/scan" \
  -H "Content-Type: application/json" \
  -d '{"ip_range": "192.168.1.1-192.168.1.255", "timeout": 2.0}'

# 2. 获取扫描结果
curl "http://localhost:8000/api/v1/cameras/network/scan-results"

# 3. 添加摄像头
curl -X POST "http://localhost:8000/api/v1/cameras/network/add" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "camera_003",
    "name": "门口摄像头",
    "rtsp_url": "rtsp://192.168.1.100:554/stream1",
    "resolution": {"width": 1920, "height": 1080},
    "fps": 30
  }'

# 4. 测试摄像头
curl -X POST "http://localhost:8000/api/v1/cameras/network/test" \
  -H "Content-Type: application/json" \
  -d '{"rtsp_url": "rtsp://192.168.1.100:554/stream1"}'
```

### 方法三：Python 脚本

```python
from edge.src.network_camera_scanner import NetworkCameraScanner

scanner = NetworkCameraScanner()

# 扫描网络
results = scanner.scan_network("192.168.1.1-192.168.1.255", timeout=2.0)

# 查看结果
for camera in results:
    print(f"找到摄像头：{camera['ip']}")
    print(f"RTSP 地址：{camera['rtsp_url']}")
```

## 📁 相关文件

### 后端文件
- `edge/src/network_camera_scanner.py` - 扫描器核心
- `edge/src/api_server.py` - API 端点
- `edge/src/config_manager.py` - 配置管理
- `edge/src/camera_manager.py` - 摄像头管理

### 前端文件
- `frontend/src/views/NetworkCameraManager.vue` - 主界面
- `frontend/src/views/DeviceManagement.vue` - 设备管理集成
- `frontend/src/router/index.js` - 路由配置
- `frontend/src/api/index.js` - API 封装

### 文档文件
- `docs/网络摄像头自动添加指南.md` - 详细使用指南
- `NETWORK_CAMERA_FEATURE.md` - 本文档

## ⚙️ 配置说明

### 摄像头配置参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| id | string | - | 唯一标识（必填） |
| name | string | - | 摄像头名称（必填） |
| source | string | - | RTSP 地址（必填） |
| resolution.width | int | 1920 | 宽度 |
| resolution.height | int | 1080 | 高度 |
| fps | int | 30 | 帧率 |
| exposure | float | -4 | 曝光值 |
| contrast | int | 50 | 对比度 |
| brightness | int | 50 | 亮度 |

### 配置文件位置
`edge/config/config.yaml`

## 🐛 故障排查

### 问题 1：找不到"扫描网络摄像头"按钮
**原因**：前端未正确加载或路由未配置  
**解决**：
1. 检查路由配置：`frontend/src/router/index.js`
2. 确认 `NetworkCameraManager.vue` 文件存在
3. 重启前端服务

### 问题 2：扫描不到摄像头
**可能原因**：
- IP 范围错误
- 摄像头未通电或未联网
- 防火墙阻止

**解决方法**：
1. 确认 IP 范围正确（使用 `ipconfig` 查看本机网段）
2. 检查摄像头电源和网络连接
3. 临时关闭防火墙测试

### 问题 3：无法连接 RTSP 流
**可能原因**：
- RTSP 地址格式错误
- 需要认证但未提供用户名密码
- 端口被防火墙阻止

**解决方法**：
1. 使用 VLC 播放器测试 RTSP 地址
2. 添加认证信息：`rtsp://user:pass@ip:port/stream`
3. 检查防火墙设置

## 🚀 性能优化建议

### 扫描优化
1. **缩小 IP 范围**：只扫描实际使用的网段
2. **调整超时时间**：根据网络质量调整（默认 2 秒）
3. **避开网络高峰**：在空闲时段扫描

### 运行优化
1. **合理数量**：建议不超过 8 个网络摄像头
2. **降低分辨率**：使用子码流（720p）代替主码流
3. **优化帧率**：25-30 FPS 足够大多数场景

## 🔒 安全建议

1. **修改默认密码**：所有摄像头都应修改默认管理员密码
2. **启用认证**：RTSP 流应配置用户名密码认证
3. **网络隔离**：将摄像头放在独立的 VLAN 中
4. **定期更新**：及时更新摄像头固件

## 📊 API 完整列表

| 端点 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/cameras/network/scan` | POST | 扫描网络摄像头 | ✅ |
| `/cameras/network/scan-results` | GET | 获取扫描结果 | ✅ |
| `/cameras/network/add` | POST | 添加摄像头 | ✅ |
| `/cameras/network/test` | POST | 测试摄像头 | ✅ |
| `/cameras` | GET | 获取摄像头列表 | ✅ |
| `/camera/{id}/status` | GET | 获取摄像头状态 | ✅ |

## 📝 测试脚本

运行测试：
```bash
python test_network_camera_scanner.py
```

## 🎯 下一步计划

- [ ] 支持 ONVIF 协议自动发现
- [ ] 支持批量添加和导入
- [ ] 增加摄像头预览功能
- [ ] 支持更多品牌和 URL 格式
- [ ] 添加摄像头分组管理

## 📞 技术支持

如有问题，请参考完整文档：`docs/网络摄像头自动添加指南.md`
