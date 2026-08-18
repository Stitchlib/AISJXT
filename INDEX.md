# AI视觉质检系统 - 完整索引

## 📚 文档导航

### 🚀 快速开始系列

| 文档 | 用途 | 适合人群 | 阅读时间 |
|------|------|----------|----------|
| [QUICK_START.md](QUICK_START.md) | 5 分钟快速部署 | 所有用户 | 5 分钟 |
| [README.md](README.md) | 项目介绍和功能概览 | 所有用户 | 10 分钟 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Docker 部署详细指南 | 运维人员 | 20 分钟 |

### 📖 开发指南系列

| 文档 | 用途 | 适合人群 | 阅读时间 |
|------|------|----------|----------|
| [docs/功能增强开发报告.md](docs/功能增强开发报告.md) | 功能增强开发详情 | 开发人员 | 30 分钟 |
| [docs/功能增强完成总结.md](docs/功能增强完成总结.md) | 功能增强完整总结 | 所有人员 | 20 分钟 |
| PROJECT_COMPLETION_REPORT.md | 项目完成报告 | 管理人员 | 25 分钟 |

### 🔧 运维手册系列

| 文档 | 用途 | 适合人群 | 阅读时间 |
|------|------|----------|----------|
| [MAINTENANCE.md](MAINTENANCE.md) | 日常运维和故障排查 | 运维人员 | 40 分钟 |
| [ROADMAP.md](ROADMAP.md) | 技术发展路线图 | 技术人员 | 30 分钟 |

---

## 🗂️ 文件结构索引

### 根目录文件

```
AISJZJRJT/
├── README.md                          # 项目主文档 ⭐必读
├── QUICK_START.md                     # 快速启动指南 ⭐必读
├── DEPLOYMENT.md                      # Docker 部署指南
├── MAINTENANCE.md                     # 运维手册
├── ROADMAP.md                         # 发展路线图
├── PROJECT_COMPLETION_REPORT.md       # 项目完成报告
├── docker-compose.yml                 # Docker 编排文件
├── Dockerfile.backend                 # 后端 Dockerfile
├── Dockerfile.frontend                # 前端 Dockerfile
├── deploy-docker.bat                  # Windows 快速部署脚本 ⭐推荐
├── validate-all-features.py           # 完整功能验证脚本
├── test-new-features.bat              # Windows 测试工具
└── .github/workflows/ci.yml.example   # CI/CD配置示例
```

### 后端目录 (edge/)

```
edge/
├── main.py                            # 后端主程序 ⭐入口
├── requirements.txt                   # Python 依赖
├── config/
│   ├── config.yaml                    # 主配置文件 ⭐重要
│   └── email_config.yaml.example      # 邮件配置示例
├── src/
│   ├── database.py                    # 数据库管理器 ⭐新增
│   ├── data_exporter.py               # 数据导出器 ⭐新增
│   ├── jwt_auth.py                    # JWT 认证 ⭐新增
│   ├── user_manager.py                # 用户管理 ⭐新增
│   ├── email_notifier.py              # 邮件通知 ⭐新增
│   ├── websocket_optimizer.py         # WebSocket 优化 ⭐新增
│   ├── api_server.py                  # API 服务器
│   ├── camera_manager.py              # 摄像头管理
│   ├── defect_detector.py             # 缺陷检测
│   ├── model_manager.py               # 模型管理
│   └── ...                            # 其他模块
├── data/                              # 数据目录（运行时生成）
│   ├── inspection.db                  # SQLite 数据库
│   └── export/                        # 导出文件
├── logs/                              # 日志目录（运行时生成）
│   └── app.log
└── models/                            # 模型目录（运行时生成）
    └── yolov8n.pt
```

### 前端目录 (frontend/)

```
frontend/
├── package.json                       # Node.js 依赖
├── vite.config.js                     # Vite 配置
├── index.html                         # HTML 入口
├── nginx.conf                         # Nginx 配置 ⭐新增
├── public/
│   ├── sw.js                          # Service Worker ⭐新增
│   ├── manifest.json                  # PWA Manifest ⭐新增
│   └── offline.html                   # 离线页面 ⭐新增
├── src/
│   ├── main.js                        # 应用入口
│   ├── App.vue                        # 根组件
│   ├── views/
│   │   ├── Dashboard.vue              # 仪表盘
│   │   ├── Login.vue                  # 登录页 ⭐新增
│   │   └── ...                        # 其他视图
│   ├── components/
│   │   ├── PWAInstallPrompt.vue       # PWA 安装提示 ⭐新增
│   │   └── ...                        # 其他组件
│   ├── utils/
│   │   ├── pwa.js                     # PWA 工具 ⭐新增
│   │   ├── errorReporting.js          # 错误上报 ⭐新增
│   │   └── ...                        # 其他工具
│   ├── api/
│   │   ├── index.js                   # API 接口
│   │   └── client.js                  # API 客户端
│   └── router/
│       └── index.js                   # 路由配置
└── dist/                              # 构建输出（运行时生成）
```

### 文档目录 (docs/)

```
docs/
├── 功能增强开发报告.md                # 开发过程记录
├── 功能增强完成总结.md                # 功能增强总结
└── ...                                # 其他技术文档
```

### 测试目录 (tests/)

```
tests/
├── test_new_features.py               # 新功能测试 ⭐新增
└── ...                                # 其他测试
```

---

## 🔑 关键概念索引

### A
- **API 端点** - [README.md](README.md#api-端点), [DEPLOYMENT.md](DEPLOYMENT.md#访问地址)
- **Access Token** - [docs/功能增强开发报告.md](docs/功能增强开发报告.md#jwt-双-token-机制)

### B
- **备份恢复** - [MAINTENANCE.md](MAINTENANCE.md#数据备份与恢复), [deploy-docker.bat](deploy-docker.bat)

### D
- **Docker 部署** - [DEPLOYMENT.md](DEPLOYMENT.md), [docker-compose.yml](docker-compose.yml)
- **数据库管理** - [edge/src/database.py](edge/src/database.py)
- **错误监控** - [README.md](README.md#错误监控-⭐新增), [frontend/src/utils/errorReporting.js](frontend/src/utils/errorReporting.js)

### F
- **服务编排** - [docker-compose.yml](docker-compose.yml)
- **故障排查** - [MAINTENANCE.md](MAINTENANCE.md#故障排查)

### G
- **功能验证** - [validate-all-features.py](validate-all-features.py)

### H
- **健康检查** - [MAINTENANCE.md](MAINTENANCE.md#系统健康监控)

### J
- **JWT 认证** - [edge/src/jwt_auth.py](edge/src/jwt_auth.py), [README.md](README.md#用户认证-⭐新增)

### M
- **邮件通知** - [edge/src/email_notifier.py](edge/src/email_notifier.py), [MAINTENANCE.md](MAINTENANCE.md#邮件发送失败)
- **模型管理** - [edge/src/model_manager.py](edge/src/model_manager.py)

### P
- **PWA 支持** - [README.md](README.md#pwa-支持-⭐新增), [frontend/public/sw.js](frontend/public/sw.js)
- **性能优化** - [MAINTENANCE.md](MAINTENANCE.md#性能优化)

### Q
- **快速开始** - [QUICK_START.md](QUICK_START.md)

### R
- **日志管理** - [MAINTENANCE.md](MAINTENANCE.md#日志管理)
- **路线图** - [ROADMAP.md](ROADMAP.md)

### S
- **Service Worker** - [frontend/public/sw.js](frontend/public/sw.js)
- **数据持久化** - [README.md](README.md#数据持久化-⭐新增)

### W
- **WebSocket 优化** - [edge/src/websocket_optimizer.py](edge/src/websocket_optimizer.py)

### X
- **系统监控** - [MAINTENANCE.md](MAINTENANCE.md#监控与告警)

### Y
- **用户认证** - [README.md](README.md#用户认证-⭐新增), [edge/src/user_manager.py](edge/src/user_manager.py)

### Z
- **资源监控** - [MAINTENANCE.md](MAINTENANCE.md#资源监控)

---

## 🎯 常见任务快速查找

### 部署相关

| 任务 | 文档位置 | 命令/脚本 |
|------|----------|-----------|
| Docker 快速部署 | [DEPLOYMENT.md](DEPLOYMENT.md#快速开始) | `deploy-docker.bat` |
| 本地开发环境 | [QUICK_START.md](QUICK_START.md#方式二本地运行) | `python main.py` + `npm run dev` |
| 查看服务状态 | [MAINTENANCE.md](MAINTENANCE.md#服务状态检查) | `docker-compose ps` |
| 重启服务 | [MAINTENANCE.md](MAINTENANCE.md#日常运维) | `docker-compose restart` |

### 配置相关

| 任务 | 文档位置 | 文件 |
|------|----------|------|
| 配置邮件通知 | [MAINTENANCE.md](MAINTENANCE.md#邮件发送失败) | `edge/config/email_config.yaml` |
| 修改 JWT 密钥 | [PROJECT_COMPLETION_REPORT.md](PROJECT_COMPLETION_REPORT.md#安全提醒) | 环境变量 |
| 调整日志级别 | [MAINTENANCE.md](MAINTENANCE.md#日志管理) | `edge/config.yaml` |
| CORS 配置 | [MAINTENANCE.md](MAINTENANCE.md#前端页面空白) | `edge/config.yaml` |

### 运维相关

| 任务 | 文档位置 | 方法 |
|------|----------|------|
| 数据备份 | [MAINTENANCE.md](MAINTENANCE.md#数据备份) | `backup.sh` 或 `deploy-docker.bat [9]` |
| 数据恢复 | [MAINTENANCE.md](MAINTENANCE.md#数据恢复) | 手动恢复或 `restore.sh` |
| 查看日志 | [MAINTENANCE.md](MAINTENANCE.md#日志管理) | `docker-compose logs -f` |
| 性能优化 | [MAINTENANCE.md](MAINTENANCE.md#性能优化) | 数据库清理、Redis 缓存等 |
| 故障排查 | [MAINTENANCE.md](MAINTENANCE.md#故障排查) | 按症状查找解决方案 |

### 开发相关

| 任务 | 文档位置 | 说明 |
|------|----------|------|
| API 文档 | http://localhost:8000/api/v1/docs | Swagger UI |
| 添加新端点 | [edge/src/api_server.py](edge/src/api_server.py) | FastAPI 路由 |
| 前端组件开发 | [frontend/src/components/](frontend/src/components/) | Vue 3 Composition API |
| 数据库操作 | [edge/src/database.py](edge/src/database.py) | SQLite CRUD |

### 测试相关

| 任务 | 文档位置 | 命令 |
|------|----------|------|
| 完整功能验证 | [validate-all-features.py](validate-all-features.py) | `python validate-all-features.py` |
| 新功能测试 | [tests/test_new_features.py](tests/test_new_features.py) | `test-new-features.bat` |
| 邮件测试 | [MAINTENANCE.md](MAINTENANCE.md#邮件发送失败) | API 端点或脚本 |

---

## 📊 API 端点索引

### 用户认证（5 个）

| 端点 | 方法 | 说明 | 文档 |
|------|------|------|------|
| `/api/v1/auth/register` | POST | 用户注册 | [README.md](README.md#用户认证端点) |
| `/api/v1/auth/login` | POST | 用户登录 | [README.md](README.md#用户认证端点) |
| `/api/v1/auth/refresh` | POST | 刷新 Token | [README.md](README.md#用户认证端点) |
| `/api/v1/auth/me` | GET | 获取当前用户 | [README.md](README.md#用户认证端点) |
| `/api/v1/auth/password` | PUT | 修改密码 | [README.md](README.md#用户认证端点) |

### 数据查询（4 个）

| 端点 | 方法 | 说明 | 文档 |
|------|------|------|------|
| `/api/v1/detection-results` | GET | 分页查询检测结果 | [README.md](README.md#数据查询端点) |
| `/api/v1/detection-results/{id}` | GET | 获取单条结果详情 | [README.md](README.md#数据查询端点) |
| `/api/v1/statistics/daily` | GET | 每日统计数据 | [README.md](README.md#数据查询端点) |
| `/api/v1/export/daily` | POST | 导出日报数据 | [README.md](README.md#数据查询端点) |

### 邮件通知（3 个）

| 端点 | 方法 | 说明 | 文档 |
|------|------|------|------|
| `/api/v1/email/test` | POST | 测试邮件通知 | [README.md](README.md#邮件通知端点) |
| `/api/v1/email/send-alert` | POST | 发送告警邮件 | [README.md](README.md#邮件通知端点) |
| `/api/v1/email/send-report` | POST | 发送报告邮件 | [README.md](README.md#邮件通知端点) |

---

## 🆘 问题快速诊断

### 症状 → 解决方案映射

| 症状 | 可能原因 | 解决方案位置 |
|------|----------|--------------|
| 后端无法启动 | 配置错误/端口占用 | [MAINTENANCE.md](MAINTENANCE.md#后端服务无法启动) |
| 前端页面空白 | 构建失败/CORS 问题 | [MAINTENANCE.md](MAINTENANCE.md#前端页面空白) |
| 邮件发送失败 | SMTP 配置错误 | [MAINTENANCE.md](MAINTENANCE.md#邮件发送失败) |
| WebSocket 断开 | Nginx 配置问题 | [MAINTENANCE.md](MAINTENANCE.md#websocket-连接断开) |
| 数据库锁定 | 并发写入冲突 | [MAINTENANCE.md](MAINTENANCE.md#数据库锁定) |
| Docker 启动失败 | 资源不足/配置错误 | [DEPLOYMENT.md](DEPLOYMENT.md#故障排查) |
| PWA 无法安装 | 浏览器不支持 | [QUICK_START.md](QUICK_START.md#pwa-安装可选) |

---

## 🎓 学习路径建议

### 新手入门（第 1 周）

1. 阅读 [README.md](README.md) - 了解项目概况
2. 按照 [QUICK_START.md](QUICK_START.md) 快速部署
3. 使用默认账户登录体验
4. 运行 `test-new-features.bat` 验证功能

### 开发人员（第 2-3 周）

1. 精读 [docs/功能增强开发报告.md](docs/功能增强开发报告.md)
2. 研究核心模块源码
3. 尝试添加新功能或修改现有功能
4. 编写单元测试

### 运维人员（第 4 周）

1. 深入学习 [DEPLOYMENT.md](DEPLOYMENT.md)
2. 掌握 [MAINTENANCE.md](MAINTENANCE.md) 所有技能
3. 模拟故障场景演练
4. 建立监控和告警体系

### 管理人员

1. 浏览 [README.md](README.md) 了解功能
2. 阅读 [PROJECT_COMPLETION_REPORT.md](PROJECT_COMPLETION_REPORT_REPORT.md) 了解成果
3. 查看 [ROADMAP.md](ROADMAP.md) 了解规划
4. 评估商业价值和应用场景

---

## 📞 获取帮助

### 文档资源
- **快速指南**: [QUICK_START.md](QUICK_START.md)
- **完整文档**: [PROJECT_COMPLETION_REPORT.md](PROJECT_COMPLETION_REPORT_REPORT.md)
- **API 文档**: http://localhost:8000/api/v1/docs

### 社区资源
- GitHub Issues（如开源）
- 技术讨论群
- Stack Overflow 标签

---

**最后更新**: 2026-03-24  
**版本**: v2.0.0  
**维护**: AI视觉质检系统团队
