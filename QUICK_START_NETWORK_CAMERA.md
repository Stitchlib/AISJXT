# 网络摄像头快速启动

> 本文档内容已合并至 **[NETWORK_CAMERA_FEATURE.md](./NETWORK_CAMERA_FEATURE.md)**，
> 请直接查看该文档获取最新、准确的 API、端口与配置说明。

要点速记：
- 前端开发地址：`http://localhost:3000/network-cameras`（`vite.config.js` 的 `server.port=3000`）
- Docker 部署地址：`http://localhost/network-cameras`
- 配置持久化于 `edge/config/config.json`
- 扫描端点为 `GET /api/v1/cameras/network/scan?subnet=192.168.1`（非旧文档中的 POST）
