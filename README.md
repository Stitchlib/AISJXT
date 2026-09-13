# AI 视觉质检系统（轻量化边缘版）

[![CI](https://github.com/Stitchlib/AISJXT/actions/workflows/ci.yml/badge.svg)](https://github.com/Stitchlib/AISJXT/actions/workflows/ci.yml)

基于深度学习的工业外观缺陷检测系统：边缘侧实时推理 + 云端/本地 Web 看板，覆盖设备管理、实时质检、模型版本、报表导出、告警与用户权限。

> **状态说明（重要）**：本仓库早期文档存在大量"100% 完成 / 生产就绪"的虚构声明，实际业务源码当时为空。
> 当前代码为**从零真实构建、可运行、测试覆盖**的版本。所有"已实现"项均以 `pytest` 与前端构建产物为准。

## 质量门禁（CI）

| 门禁 | 标准 |
|------|------|
| 后端测试覆盖率 | `pytest --cov=edge/src --cov-fail-under=75`（当前实测约 81%，随阶段递增） |
| 静态检查 | `ruff check edge/ tests/`（E4/E7/E9/F：未定义名称、未使用导入、语法级错误） |
| 前端 | `npm run lint` + 单测 + `npm run build` |
| 镜像构建 | backend / frontend Docker 多阶段构建 |

> perf（百万行性能验收）与 network_scan（依赖真实局域网摄像头）用例不在 CI 门禁内，本地/验收机专项运行。

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
| 摄像头 | `GET/POST/PUT/DELETE /cameras`、`GET /cameras/network/scan`、`PUT /cameras/{id}` 支持 `roi`（归一化检测区域，G6） |
| 配置 | `GET/PUT /config` |
| 检测 | `GET /detection-results`、`GET /detection-results/statistics`、`GET /detection-results/export` |
| 检测控制 | `POST /inspection/start`（`camera_id` 支持单个/逗号列表/`all`，多摄并发，G5）、`POST /inspection/stop`（可单停一摄）、`GET /inspection/status`（含 `running_cameras` 分摄计数） |
| 模型 | `GET/POST /model-versions/upload`、`POST /model-versions/{id}/activate`、`DELETE /model-versions/{id}`、`GET /model-versions/export-samples`（operator+；把已判定 confirmed/false_positive 的缺陷帧 + 标注导出为 YOLO 目录 zip，受 `sample_export_limit` 配额保护） |
| 报表 | `GET /reports/summary`、`GET /reports/export`、`GET /reports/batch/{batch_id}`（按批次聚合） |
| 告警 | `GET/POST/PUT/DELETE /alerts/rules`、`GET /alerts/events`、`POST /alerts/events/{id}/acknowledge`、`POST /alerts/events/{id}/verdict`（人工判定：确认/误报/漏报）、`POST /alerts/rules/{id}/test`（Webhook 连通性测试） |
| 用户 | `GET/POST/PUT/DELETE /users`（仅 admin）、`PUT /users/{id}/password`（改密码：本人需验旧口令） |
| 审计 | `GET /audit`（仅 admin，管理操作流水） |
| 令牌 | `POST /auth/refresh`（滑动过期刷新，免中途登出） |
| 视频流 | `GET /cameras/stream-ticket`（换取一次性短时效 ticket，MJPEG 用 `?ticket=` 取流，避免 JWT 落日志） |
| 实时 | `WS /ws`（start/stop 指令 + detection_result / alert / control 推送） |
| 批次/工单 | `GET/POST /batches`、`GET /batches/{id}`、`POST /batches/{id}/end`（operator+；结束批次同步解绑检测引擎当前批次）；`POST /inspection/start?batch_id=` 绑定批次后本次检测记录自动带 `batch_id` |
| 系统运维 | `POST /system/backup`、`GET /system/backups`（仅 admin；SQLite 在线备份 + 保留最近 N 份，N 默认 7 可配） |

交互式文档：`http://localhost:8000/docs`（Swagger）。除登录外均需 `Authorization: Bearer <token>`。

---

## 测试

```bash
.venv\Scripts\python.exe -m pytest tests/ -p no:logging -q
```

覆盖：认证与 401 守卫、摄像头 CRUD、配置读写、WebSocket→检测→持久化→查询全链路、
告警规则触发与确认、报表聚合与导出、用户 RBAC、数据库批量写入性能（WAL + synchronous=NORMAL 优化）。
第二期（第二批）新增覆盖：批次/工单创建与绑定（`tests/test_stage2b.py`）、告警人工判定与误报率统计、
多渠道 Webhook 通知（generic/钉钉/飞书/企业微信，含 mock 单测）、schema 版本化迁移幂等、
SQLite 在线备份与超额清理（`prune_backups` 保留最近 N 份 + 审计）。

---

## 部署

```bash
docker compose up -d --build
# 前端 http://localhost   后端 http://localhost:8000/docs
```

`docker-compose.yml` 不依赖 Redis 等外部组件（SQLite 内嵌）。如需横向扩展可将 `database.py` 替换为 PostgreSQL 实现。

---

## 安全与运维

系统按"可上产线"目标加固，关键安全姿态如下（均有对应测试覆盖）：

- **密钥与口令治理（H5）**：JWT 签名密钥 `secret_key`、管理员初始口令均支持并**强烈建议**通过环境变量覆盖
 （`AIQC_SECRET_KEY` / `AIQC_ADMIN_PASSWORD`）。未覆盖时启动日志明确告警，不静默放行。
- **配置接口脱敏与越权防护（H1/M5）**：`GET /config` 仅返回白名单字段（阈值、fps、缺陷类型等），
  `secret_key` 与明文 SMTP 口令永不外泄；`PUT /config` 仅 admin 可调，viewer 返回 403。
- **WebSocket 鉴权与一次性票据（H2/1.3）**：`/ws` 握手支持三种方式（按优先级）：
  `?ticket=<一次性票据>`（推荐，先 `POST /api/v1/ws-ticket` 用 Bearer 令牌换取，30 秒有效、
  绑定用户身份、一次性消费，JWT 不再进入 URL/访问日志）→ `?token=<JWT>`（兼容保留）→
  首帧 `{"action":"auth","token":...}` 兜底。未授权立即关闭（码 4401）；
  WS 控制面与 HTTP 权限一致：启停检测需 operator+（viewer 收到码 4403）。
- **权限矩阵（RBAC，1.1/H2）**：三角色最小权限，越权尝试写入审计日志（`action=rbac_denied`）。

  | 操作 | viewer | operator | admin |
  |------|--------|----------|-------|
  | 只读（列表/状态/报表/审计查看） | ✅ | ✅ | ✅ |
  | 检测启停（HTTP + WS）、摄像头增改普通字段、设当前、发现、连接测试 | ❌ 403 | ✅ | ✅ |
  | 摄像头来源/凭据修改 | ❌ 403 | ❌ 403 | ✅ |
  | 摄像头删除、用户管理、配置修改、备份 | ❌ 403 | ❌ 403 | ✅ |

- **摄像头凭据脱敏（1.2/H3）**：所有摄像头 API 响应中 `source` 一律为掩码值
  （`rtsp://user:***@host`，另附 `source_masked` 字段），明文密码只存在于内部取流链路与配置；
  前端把掩码值原样回传时后端视为"未修改"，绝不写穿真实凭据；编辑对话框中账号/密码留空=不修改。
- **CORS 收敛（M8）**：`allow_origins` 由 `AIQC_ALLOWED_ORIGINS`（逗号分隔）注入，默认空（仅同源）；
  Nginx 反代场景下无需跨域。
- **视频流鉴权（M7）**：MJPEG 流不再使用 `?token=<JWT>`（避免令牌进入访问日志/浏览器历史），
  改为先换取一次性 60s 短时效 `stream-ticket`，URL 用 `?ticket=`。
- **登录限流（M6）**：同账号连续 5 次失败锁定 10 分钟（内存计数，单实例足够）；用户可改自身口令（需验旧口令）、
  admin 可重置他人口令；禁止删除自己与最后一个管理员。
- **审计日志（L3）**：登录、配置变更、用户增删、模型激活等管理操作记入 `audit_logs`，
  admin 可在「用户管理 → 审计日志」查看流水（who/what/when/ip）。
- **配置健壮性（M12）**：`config.json` 解析失败时自动备份为 `config.json.corrupt-{ts}` 并标记降级，
  `/system-health` 暴露 `config_degraded` 状态，绝不静默回退到空配置导致配置清零。
- **配置文件权限（部署要求）**：`edge/config/config.json` 含摄像头凭据与 SMTP 口令，生产部署须限制为
  `chmod 600 config.json`（属主可读写，Windows 下可对文件设置仅服务账户可读），并避免提交到版本库。
- **监控指标（L9）**：`/system-health` 输出推理延迟 P50/P95、帧丢帧率、WS 在线连接数、DB 大小与写入 QPS、
  检测器模式与配置状态，供仪表盘与压测观察。

### 配置（环境变量，生产必设）

| 变量 | 说明 |
|------|------|
| `AIQC_SECRET_KEY` | JWT 签名密钥（**必设**，否则可被伪造 admin 令牌） |
| `AIQC_ADMIN_PASSWORD` | 覆盖默认管理员口令 `admin123` |
| `AIQC_ALLOWED_ORIGINS` | CORS 可信来源，逗号分隔；留空=仅同源 |
| `AIQC_DB_PATH` / `AIQC_MODEL_PATH` | 容器内数据 / 权重路径（覆盖配置文件中的宿主绝对路径） |
| `AIQC_DATA_RETENTION_DAYS` / `AIQC_INSPECTION_INTERVAL_MS` / `AIQC_MAX_UPLOAD_MB` / `AIQC_TOKEN_EXPIRE_MINUTES` | 数据保留天数 / 检测节拍(ms) / 模型上传上限(MB) / 令牌时效(分) |
| `AIQC_BACKUP_DIR` / `AIQC_BACKUP_RETENTION` | SQLite 在线备份目录（默认 `data/backups`）/ 备份保留份数（默认 7） |
| `AIQC_IMAGE_RETENTION_DAYS` / `AIQC_IMAGE_QUOTA_GB` | 缺陷图片留存天数（默认 7）/ 图片配额 GB（默认 2，超配额触发清理） |

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
4. **多渠道 Webhook 通知（第二期 G3）**：告警规则支持 `webhook_url` + `webhook_type`（generic/dingtalk/feishu/wecom），
   命中阈值后经 `asyncio.to_thread` 异步 POST，失败仅记日志并重试 1 次（不阻塞主流程）；可通过 `POST /alerts/rules/{id}/test` 发一次连通性测试。
   纯标准库 `urllib` 实现，无额外依赖。
5. **缺陷图片留存（第二期 G1）**：命中缺陷时落盘原图/裁剪图至 `data/defects/`，受 `image_retention_days` 与 `image_quota_gb`（默认 7 天 / 2GB）配额治理，
   启动期与每 6 小时周期性清理过期/超配额图片；`detection_results.image_path` 指向留存图，看板可按事件回看。
6. **批次/工单追溯（第二期 G4）**：`POST /inspection/start?batch_id=` 可绑定生产批次，本次检测记录自动带 `batch_id`（兼容 NULL）；
   `GET /reports/batch/{id}` 按批次聚合不良率/缺陷数/按类型分布，支持产线级质量追溯。
7. **备份与迁移（第二期 G7）**：`POST /system/backup` 用 `sqlite3` backup API 做在线热备至 `data/backups/`，保留最近 N 份（默认 7，可配 `backup_retention`）；
   schema 变更统一纳入版本化迁移注册表（幂等），`schema_version` 表记录当前版本，启动期自动补齐旧库列/索引且不破坏既有数据。
8. **训练样本导出（第二期 1.3）**：模型迭代闭环收口——`GET /model-versions/export-samples` 把已人工判定（confirmed/false_positive）的缺陷帧 + 标注导出为 YOLO 目录结构（images/ + labels/ + classes.txt + data.yaml），直接可用于 `ultralytics train`；单次样本数受 `sample_export_limit`（默认 2000，可配）配额保护。
9. **多摄像头并发检测（第二期 G5）**：引擎重构为任务字典（每摄一个检测任务），`start?camera_id=a,b` 或 `camera_id=all` 并发启动、可运行中追加；共享帧总线 + 共享检测器（推理加锁串行）；`status.running_cameras` 分摄计数；单摄连续异常自动摘除，不影响其他摄像头；单摄无参启动行为不变。
10. **ROI 检测区域（第二期 G6）**：摄像头配置 `roi`（归一化矩形列表，`PUT /cameras/{id}`），检测前对 ROI 并集外画面涂黑掩膜 + 检出后按 bbox 中心二次过滤（区域外目标不计入结果），坐标保持原图像素（前端画框位置一致）；视频流叠加 ROI 边界；设备管理页支持拖拽画框编辑；不配置则全画面检测（行为不变）。
11. **告警冷却/聚合与异步通知（第三期 2.1/2.2）**：规则可配 `cooldown_seconds`（0=不冷却，旧行为兼容）与 `silence_until`；冷却窗口内重复命中不重复通知，仅累加事件 `repeat_count`，恢复后可发恢复通知。通知经有界队列（默认 1000）由 worker 异步投递邮件/Webhook，外部服务故障不阻塞检测节拍，关停时 drain。
12. **WebSocket 订阅过滤（第三期 2.3）**：`/ws?subscribe=cam_a,cam_b` 只收指定摄像头的 `detection_result`（空=全量，向后兼容）；每客户端独立发送队列，3s 发送超时或队列满即摘除该慢消费者，不影响其他客户端。
13. **指标口径（第三期 3.2）**：单帧 `defect_rate` = 该帧缺陷框数 / 检出对象总数（`metric_version=2` 缺陷专用模型时即缺陷框占比；COCO/仿真基线为 1）；批次与按日/周/月聚合的不良率 = **缺陷帧数 / 总帧数**（一帧多框只计 1 个缺陷帧），`/reports/summary` 同时给出 `defect_frame_rate` 显式别名；前端质检报告页与历史记录页均有口径说明。
14. **摄像头配置单一数据源（第三期 3.1）**：摄像头持久化字段唯一存放于 `config.json`（ConfigManager），CameraManager 只做现场物化视图与网络发现，新增/更新/删除/激活均落盘配置，杜绝内存态与配置文件双写漂移。
4. **PWA / 双因子 / 日志上报**：早期文档提及但本版未实现，如需要可后续迭代。

---

## 开发约定

- 模块化：`edge/src` 各模块只负责单一职责，跨模块协作经 `inspection_engine` 与路由层，禁止循环依赖。
- 数据契约集中在 `edge/src/models.py`，前后端以 Pydantic 模型为准。
- 新增后端模块：在 `src/` 实现 → 在 `src/routers/` 暴露 → 在 `main.py` 注册；受保护路由加 `Depends(get_current_user)`。
- 配置变更走 `config_manager`，持久化走 `database`，实时推送走 `websocket_manager`。
