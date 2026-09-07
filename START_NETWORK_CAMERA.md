# 网络摄像头 — 安装与启动

> 本文档内容已合并至 **[NETWORK_CAMERA_FEATURE.md](./NETWORK_CAMERA_FEATURE.md)**，
> 请查看该文档获取准确的 API、端点与故障排查说明。

常用操作速记：
- **启动 / 重启后端**：`cd edge && python main.py`（Docker 部署用 `docker-compose restart backend`）
- **启动前端（开发）**：`cd frontend && npm run dev`（监听 `http://localhost:3000`）
- **验证后端 API**：`http://localhost:8000/api/v1/docs`
- **网络摄像头页面**：`http://localhost:3000/network-cameras`

> 说明：旧文档中提到的 `restart-backend.bat`、`test-backend-api-endpoints.py`、
> `docs/网络摄像头自动添加指南.md` 均不存在，请勿依赖。
