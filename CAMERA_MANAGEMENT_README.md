# 摄像头管理功能

完整的摄像头生命周期管理系统，支持添加、获取、更新、删除网络摄像头，并提供自动发现和测试功能。

## 🚀 快速开始

### 方式 1: 使用启动脚本（推荐）

```bash
# Windows
test-camera.bat

# 选择测试模式:
# 1. 快速验证
# 2. 完整测试
# 3. 仅启动后端服务
```

### 方式 2: 手动启动

```bash
# 1. 启动后端服务
cd edge
python main.py

# 2. 运行测试（新开终端）
cd ..
python quick-test-camera.py
```

## 📋 功能特性

### 核心功能

- ✅ **添加摄像头** - 支持手动添加和网络扫描自动发现
- ✅ **获取列表** - 实时获取所有摄像头及其状态
- ✅ **更新配置** - 动态修改摄像头参数（名称、分辨率、帧率等）
- ✅ **删除摄像头** - 安全移除摄像头配置
- ✅ **网络扫描** - 自动发现局域网中的 RTSP 摄像头
- ✅ **连接测试** - 验证 RTSP 流是否可用

### 高级特性

- 🔒 **API 认证** - 所有操作需要 API Key 授权
- 💾 **自动保存** - 配置变更自动持久化
- 🔄 **热重载** - 更新后立即生效无需重启
- 🛡️ **错误处理** - 完善的异常处理和日志记录
- 📊 **实时状态** - 在线/离线状态监控

## 🎯 API 端点

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/v1/cameras` | 获取所有摄像头列表 |
| POST | `/api/v1/cameras/network/add` | 添加网络摄像头 |
| PUT | `/api/v1/cameras/{id}` | 更新摄像头配置 |
| DELETE | `/api/v1/cameras/{id}` | 移除摄像头 |
| POST | `/api/v1/cameras/network/scan` | 扫描网络摄像头 |
| GET | `/api/v1/cameras/network/scan-results` | 获取扫描结果 |
| POST | `/api/v1/cameras/network/test` | 测试 RTSP 连接 |

## 📖 使用示例

### 添加摄像头

```python
import requests

camera_data = {
    "id": "camera_001",
    "name": "门口摄像头",
    "rtsp_url": "rtsp://192.168.1.100:554/stream1",
    "resolution": {"width": 1920, "height": 1080},
    "fps": 30
}

response = requests.post(
    "http://localhost:8000/api/v1/cameras/network/add",
    json=camera_data
)
print(response.json())
```

### 获取摄像头列表

```python
response = requests.get("http://localhost:8000/api/v1/cameras")
cameras = response.json().get('data', [])

for camera in cameras:
    print(f"{camera['id']}: {camera['name']} - {camera['status']}")
```

### 更新摄像头配置

```python
update_data = {
    "name": "主摄像头 (已更新)",
    "fps": 25
}

response = requests.put(
    "http://localhost:8000/api/v1/cameras/camera_001",
    json=update_data
)
print(response.json())
```

### 删除摄像头

```python
response = requests.delete(
    "http://localhost:8000/api/v1/cameras/camera_001"
)
print(response.json())
```

### 扫描网络摄像头

```python
# 启动扫描
scan_params = {
    "ip_range": "192.168.1.1-192.168.1.255",
    "timeout": 2.0
}

response = requests.post(
    "http://localhost:8000/api/v1/cameras/network/scan",
    json=scan_params
)
print("扫描启动:", response.json())

# 等待并获取结果
import time
time.sleep(5)

response = requests.get(
    "http://localhost:8000/api/v1/cameras/network/scan-results"
)
print("扫描结果:", response.json())
```

## 🧪 测试

### 快速验证

```bash
python quick-test-camera.py
```

输出示例：
```
==================================================
摄像头管理 API 快速测试
==================================================

[1] 获取摄像头列表...
状态码：200
摄像头数量：2

[2] 添加测试摄像头...
状态码：200
消息：网络摄像头添加成功

[3] 再次获取摄像头列表...
摄像头数量：3

[4] 更新摄像头配置...
状态码：200
消息：摄像头配置已更新

[5] 移除摄像头...
状态码：200
消息：摄像头已移除

[6] 最终摄像头列表...
摄像头数量：2

==================================================
测试完成！
==================================================
```

### 完整测试

```bash
python test-camera-management.py
```

包含交互式测试和详细报告。

## 📁 项目结构

```
AISJZJRJT/
├── edge/
│   ├── src/
│   │   ├── config_manager.py      # 配置管理器
│   │   ├── api_server.py          # API 服务器
│   │   ├── camera_manager.py      # 摄像头管理器
│   │   └── network_camera_scanner.py  # 网络摄像头扫描器
│   └── config/
│       └── config.yaml            # 摄像头配置文件
├── frontend/
│   └── src/
│       ├── api/
│       │   └── index.js           # API 客户端
│       └── views/
│           └── NetworkCameraManager.vue  # 前端管理界面
├── docs/
│   ├── 摄像头管理功能开发报告.md   # 技术开发报告
│   ├── 摄像头管理功能测试指南.md   # 详细测试指南
│   └── 摄像头管理能力提升总结.md   # 功能总结文档
├── test-camera-management.py      # 完整测试脚本
├── quick-test-camera.py          # 快速验证脚本
└── test-camera.bat               # 快速启动脚本
```

## 🛠️ 配置文件

摄像头配置存储在 `edge/config/config.yaml`:

```yaml
cameras:
  - id: "camera_001"
    name: "主摄像头"
    source: 0
    resolution:
      width: 1920
      height: 1080
    fps: 30
    exposure: -4
    contrast: 50
    brightness: 50
  
  - id: "camera_002"
    name: "网络摄像头"
    source: "rtsp://192.168.1.100:554/stream1"
    resolution:
      width: 1920
      height: 1080
    fps: 30
```

## 🔧 故障排查

### 常见问题

**Q: 测试失败，提示 Connection refused**
A: 确保后端服务正在运行：`cd edge && python main.py`

**Q: 找不到摄像头**
A: 检查摄像头 ID 是否正确，或先添加摄像头

**Q: 扫描结果为空**
A: 
- 确认 IP 范围正确
- 增加超时时间
- 检查摄像头是否在线

**Q: 前端无法连接后端**
A: 
- 检查后端是否启动在 8000 端口
- 确认 CORS 配置正确
- 查看浏览器控制台错误信息

### 查看日志

```bash
# 实时查看后端日志
Get-Content edge\logs\edge-device.log -Wait -Tail 50
```

## 📚 文档

- [技术开发报告](docs/摄像头管理功能开发报告.md) - 详细的实现细节
- [测试指南](docs/摄像头管理功能测试指南.md) - 完整的测试流程
- [功能总结](docs/摄像头管理能力提升总结.md) - 总体功能概述

## 🎓 技术栈

- **后端**: Python 3.x + FastAPI
- **前端**: Vue 3 + Element Plus
- **视频流**: OpenCV
- **协议**: RTSP/ONVIF

## ⚠️ 注意事项

1. **摄像头 ID 唯一性** - 每个摄像头必须有唯一的 ID
2. **RTSP URL 格式** - 确保 URL 格式正确且可访问
3. **删除操作不可逆** - 删除前请确认
4. **网络扫描时间** - 大范围扫描可能需要较长时间

## 🔮 未来规划

- [ ] 批量操作支持
- [ ] 摄像头分组管理
- [ ] WebSocket 实时推送
- [ ] 自动健康检查
- [ ] 导入导出功能

## 📝 更新日志

### v1.0.0 (2026-03-24)

**新增功能**:
- ✅ 完整的摄像头 CRUD 操作
- ✅ 网络摄像头自动发现
- ✅ 前端管理界面
- ✅ 完善的测试体系
- ✅ 详细的技术文档

**技术改进**:
- ✅ 单例模式优化扫描器
- ✅ 热重载支持
- ✅ 错误处理增强
- ✅ API 端点 RESTful 化

---

**开发团队**: AI Assistant  
**最后更新**: 2026-03-24  
**许可证**: MIT
