# 网络摄像头功能 - 安装与启动

## ⚠️ 重要提示

**新增功能后必须重启后端服务才能生效！**

## 🔄 重启后端服务

### 方法一：使用重启脚本（推荐）

```bash
restart-backend.bat
```

### 方法二：手动重启

1. **停止当前服务**
   - 在后端服务窗口按 `Ctrl+C`
   - 或者关闭后端服务窗口

2. **重新启动**
   ```bash
   cd edge
   python main.py
   ```

3. **验证启动成功**
   - 看到日志：`Uvicorn running on http://localhost:8000`
   - 访问：http://localhost:8000/docs

## ✅ 验证 API 是否可用

运行测试脚本：
```bash
python test-backend-api-endpoints.py
```

**期望输出**：
```
✅ /cameras/network/scan - 状态码：200
✅ API 正常工作！
```

如果显示 404，说明后端未重启。

## 🚀 完整启动流程

### 首次启动或添加新功能后

1. **重启后端**
   ```bash
   restart-backend.bat
   ```

2. **启动前端**（如果未运行）
   ```bash
   cd frontend
   npm run dev
   ```

3. **访问页面**
   ```
   http://localhost:3001/network-cameras
   ```

### 日常启动（无功能变更）

如果后端和前端已经在运行，直接访问：
```
http://localhost:3001/network-cameras
```

## 🔍 故障排查

### 问题 1: 扫描失败 - 404 错误

**症状**：点击扫描按钮后提示 "Request failed with status code 404"

**原因**：后端服务未重启，新添加的 API 端点未加载

**解决方法**：
```bash
restart-backend.bat
```

### 问题 2: 无法连接到后端

**症状**：提示 "无法连接到后端服务"

**检查步骤**：
1. 确认后端正在运行
2. 检查端口是否被占用
3. 查看后端日志是否有错误

**解决方法**：
```bash
# 手动重启
cd edge
python main.py
```

### 问题 3: 页面空白或无法加载

**可能原因**：
- 前端服务未启动
- 浏览器缓存问题
- 路由配置错误

**解决方法**：
1. 确认前端服务运行：`npm run dev`
2. 清除浏览器缓存（Ctrl+Shift+Delete）
3. 硬刷新页面（Ctrl+F5）

## 📋 快速检查清单

使用前请确认：

- [ ] 后端服务已重启
- [ ] 前端服务正在运行
- [ ] 可以访问 http://localhost:8000/docs
- [ ] 可以访问 http://localhost:3001/network-cameras
- [ ] 运行 `python test-backend-api-endpoints.py` 全部通过

## 🎯 使用流程

1. **重启后端** → `restart-backend.bat`
2. **访问页面** → http://localhost:3001/network-cameras
3. **扫描摄像头** → 点击"扫描网络摄像头"
4. **添加摄像头** → 选择并填写信息
5. **测试连接** → 验证摄像头可用

## 📞 相关文档

- 功能说明：`NETWORK_CAMERA_FEATURE.md`
- 快速入门：`QUICK_START_NETWORK_CAMERA.md`
- 详细指南：`docs/网络摄像头自动添加指南.md`

---

**记住：添加新功能后一定要重启后端！** 🔄
