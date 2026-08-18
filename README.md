# AI 视觉质检系统（轻量化边缘版）

基于深度学习的工业外观缺陷检测系统：边缘侧实时推理 + 云端/本地 Web 看板，覆盖设备管理、实时质检、模型版本、报表导出、告警与用户权限。

> **状态说明（重要）**：本仓库早期文档存在大量"100% 完成 / 生产就绪"的虚构声明，实际业务源码当时为空。
> 当前代码为**从零真实构建、可运行、测试覆盖**的版本。所有"已实现"项均以 `pytest` 与前端构建产物为准。

---

## 技术栈

| 层 | 选型 |
|----|------|
| 前端 | Vue 3 (Composition API) + Vite + Element Plus + ECharts + Axios + WebSocket |
| 后端 | FastAPI + Uvicorn + Pydantic，SQLite 持久化 |
| 鉴权 | JWT (PyJWT, HS256) + pbkdf2 密码哈希 + 角色权限 (admin/operator/viewer) |
| 检测 | 真实 YOLOv8 推理（`ultralytics` 驱动）；无权重/依赖缺失时**明确标注的仿真**降级，保证全链路可演示 |
| 采集 | OpenCV 惰性导入，支持 USB/IP/RTSP；无 cv2 或设备不可用时自动降级仿真 |

---

## 项目结构

```
AISJZJRJT/
├── edge/                 # 后端（FastAPI）
│   ├── src/              # 模块化源码：models / config_manager / database /
│   │                     #   websocket_manager / camera_manager / detector /
│   │                     #   camera_capture / inspection_engine / notifier /
│   │                     #   auth / routers/*
│   ├── config/config.json
│   ├── main.py           # 入口：依赖装配 + 生命周期
│   └── requirements.txt
├── frontend/             # 前端（Vue3）
│   └── src/              # views(9) / api / store / router / utils
├── tests/                # pytest：单元 + 端到端集成（真实运行，非 mock）
├── docs/深度分析报告与开发计划.html
├── Dockerfile.backend / Dockerfile.frontend / docker-compose.yml
├── start-dev.bat         # 本地一键启动（替代损坏的旧脚本）
└── README.md
```

---

## 快速开始

### 1. 后端

```bash
cd AISJZJRJT
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r edge/requirements.txt
# 或者仅装运行所需的最小集（测试再补 pytest httpx）
.venv\Scripts\python.exe -m uvicorn edge.main:app --host 0.0.0.0 --port 8000
```

> 默认管理员：`admin / admin123`（首次启动自动种子，生产请修改 `secret_key` 与密码）。

### 2. 前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000  （已代理 /api 与 /ws 到 :8000）
```

### 3. 一键启动（Windows）

```batch
start-dev.bat
```

---

## API 概览（前缀 `/api/v1`）

| 模块 | 端点 |
|------|------|
| 健康检查 | `GET /health`、`GET /system-health` |
| 鉴权 | `POST /auth/login`、`GET /auth/me` |
| 摄像头 | `GET/POST/PUT/DELETE /cameras`、`GET /cameras/network/scan` |
| 配置 | `GET/PUT /config` |
| 检测 | `GET /detection-results`、`GET /detection-results/statistics`、`GET /detection-results/export` |
| 检测控制 | `POST /inspection/start`、`POST /inspection/stop`、`GET /inspection/status` |
| 模型 | `GET/POST /model-versions/upload`、`POST /model-versions/{id}/activate`、`DELETE /model-versions/{id}` |
| 报表 | `GET /reports/summary`、`GET /reports/export` |
| 告警 | `GET/POST/PUT/DELETE /alerts/rules`、`GET /alerts/events`、`POST /alerts/events/{id}/acknowledge` |
| 用户 | `GET/POST/PUT/DELETE /users`（仅 admin） |
| 实时 | `WS /ws`（start/stop 指令 + detection_result / alert / control 推送） |

交互式文档：`http://localhost:8000/docs`（Swagger）。除登录外均需 `Authorization: Bearer <token>`。

---

## 测试

```bash
.venv\Scripts\python.exe -m pytest tests/ -p no:logging -q
```

覆盖：认证与 401 守卫、摄像头 CRUD、配置读写、WebSocket→检测→持久化→查询全链路、
告警规则触发与确认、报表聚合与导出、用户 RBAC、数据库批量写入性能（WAL + synchronous=NORMAL 优化）。

---

## 部署

```bash
docker compose up -d --build
# 前端 http://localhost   后端 http://localhost:8000/docs
```

`docker-compose.yml` 不依赖 Redis 等外部组件（SQLite 内嵌）。如需横向扩展可将 `database.py` 替换为 PostgreSQL 实现。

---

## 已知边界 / 待补强

1. **真实检测模型**：检测流水线已接通真实 YOLOv8 推理（`detector.YoloDetector`，`ultralytics` 驱动）。
   仓库已内置并激活官方 `yolov8n.pt`（COCO 通用基线权重，`edge/model/yolov8n.pt`，经 `edge/seed_model_version.py`
   注册为模型版本 id=1 且 `active`），端到端已验证：服务以 `detector_mode=yolo` 启动，检测结果 `is_simulation=false` 落库。
   生产环境应替换为**服装瑕疵专用权重**——届时类别名（`defect.class_name`）才会是业务瑕疵类型，而非 COCO 通用类别。
   类别标签一律取自权重自带的 `names`，绝不再伪造映射到服装瑕疵名。
2. **真实摄像头**：需在装有 OpenCV 且能访问摄像头的机器上运行；否则自动仿真。
3. **邮件通知**：`notifier.py` 已实现并**经测试验证**（自包含 SMTP 服务做真实收发）。支持 `smtp_mode=ssl|starttls|plain`，
   默认关闭，需在 `/config` 开启 SMTP 并填主机/端口/账号；告警规则可绑定 `notify_email`，
   命中后落库事件并发送告警邮件（标记 `notified`）。详见 `tests/test_email_alert.py`。
4. **PWA / 双因子 / 日志上报**：早期文档提及但本版未实现，如需要可后续迭代。

---

## 开发约定

- 模块化：`edge/src` 各模块只负责单一职责，跨模块协作经 `inspection_engine` 与路由层，禁止循环依赖。
- 数据契约集中在 `edge/src/models.py`，前后端以 Pydantic 模型为准。
- 新增后端模块：在 `src/` 实现 → 在 `src/routers/` 暴露 → 在 `main.py` 注册；受保护路由加 `Depends(get_current_user)`。
- 配置变更走 `config_manager`，持久化走 `database`，实时推送走 `websocket_manager`。
