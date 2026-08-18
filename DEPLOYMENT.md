# Docker 部署指南

## 📋 前提条件

- Docker 20.10+
- Docker Compose 2.0+
- 至少 4GB 可用内存
- 至少 10GB 可用磁盘空间

## 🚀 快速开始

### 1. 构建并启动所有服务

```bash
# 构建镜像
docker-compose build

# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 2. 验证服务状态

```bash
# 检查容器状态
docker-compose ps

# 测试后端健康检查
curl http://localhost:8000/api/v1/health

# 测试前端
curl http://localhost/health
```

### 3. 访问应用

- **前端**: http://localhost
- **后端 API**: http://localhost:8000/api/v1
- **API 文档**: http://localhost:8000/api/v1/docs

## 🔧 常用命令

### 服务管理

```bash
# 启动所有服务
docker-compose up -d

# 停止所有服务
docker-compose down

# 重启所有服务
docker-compose restart

# 重启单个服务
docker-compose restart backend

# 停止并删除所有容器、网络（保留数据卷）
docker-compose down

# 停止并删除所有容器、网络和数据卷
docker-compose down -v
```

### 日志查看

```bash
# 查看所有服务日志
docker-compose logs

# 实时查看日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs backend

# 查看最近 100 行日志
docker-compose logs --tail=100 backend
```

### 进入容器

```bash
# 进入后端容器
docker-compose exec backend sh

# 进入前端容器
docker-compose exec frontend sh

# 进入 Redis 容器
docker-compose exec redis sh
```

### 构建管理

```bash
# 重新构建所有镜像
docker-compose build

# 不使用缓存重新构建
docker-compose build --no-cache

# 只构建后端
docker-compose build backend

# 只构建前端
docker-compose build frontend
```

## 📁 数据持久化

### 目录映射

以下目录会自动映射到宿主机：

```yaml
./edge/data     -> /app/data      # 数据库文件
./edge/logs     -> /app/logs      # 日志文件
./edge/models   -> /app/models    # 模型文件
./edge/config   -> /app/config    # 配置文件
redis-data      -> /data          # Redis 数据（Docker volume）
```

### 备份数据

```bash
# 备份整个数据目录
tar -czf aibc-backup-$(date +%Y%m%d).tar.gz ./edge/data ./edge/logs ./edge/models

# 备份数据库
cp ./edge/data/inspection.db ./edge/data/inspection.db.backup.$(date +%Y%m%d)
```

### 恢复数据

```bash
# 恢复数据库
cp ./edge/data/inspection.db.backup.YYYYMMDD ./edge/data/inspection.db

# 重启后端服务
docker-compose restart backend
```

## ⚙️ 配置选项

### 环境变量

可以在 `docker-compose.yml` 中修改：

```yaml
environment:
  - DATABASE_URL=sqlite:///data/inspection.db
  - LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
  - TZ=Asia/Shanghai
```

### 端口映射

默认端口：

- 前端：80
- 后端：8000
- Redis: 6379

修改示例：

```yaml
ports:
  - "8080:80"    # 前端使用 8080 端口
  - "8001:8000"  # 后端使用 8001 端口
```

## 🔍 故障排查

### 后端无法启动

```bash
# 查看详细日志
docker-compose logs backend

# 检查配置文件
docker-compose exec backend ls -la /app/config

# 检查数据库连接
docker-compose exec backend python -c "import sqlite3; print(sqlite3.connect('/app/data/inspection.db').execute('SELECT 1').fetchone())"
```

### 前端无法访问

```bash
# 检查 nginx 配置
docker-compose exec frontend nginx -t

# 检查前端日志
docker-compose logs frontend

# 测试后端连接
docker-compose exec frontend wget -qO- http://backend:8000/api/v1/health
```

### Redis 连接问题

```bash
# 检查 Redis 状态
docker-compose exec redis redis-cli ping

# 查看 Redis 日志
docker-compose logs redis

# 重启 Redis
docker-compose restart redis
```

### 数据库锁定

```bash
# 停止后端
docker-compose stop backend

# 修复数据库权限
sudo chown -R 1000:1000 ./edge/data

# 重启后端
docker-compose start backend
```

## 🛡️ 安全建议

### 1. 修改默认密码

首次登录后立即修改 admin 账户密码。

### 2. 启用 HTTPS

生产环境建议使用反向代理（如 Nginx Proxy Manager）配置 SSL 证书。

### 3. 限制网络访问

如果只在本地使用，可以限制端口访问：

```yaml
ports:
  - "127.0.0.1:8000:8000"  # 只允许本地访问
```

### 4. 定期备份

设置定时任务自动备份数据：

```bash
# crontab 示例
0 2 * * * tar -czf /backup/aibc-$(date +\%Y\%m\%d).tar.gz /path/to/aibc/edge/data
```

## 📊 性能优化

### 增加内存限制

```yaml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 1G
```

### 使用 Redis 缓存

Redis 已包含在 docker-compose 中，用于：

- WebSocket 消息缓存
- 检测结果临时存储
- 会话管理

### 静态资源 CDN

生产环境可以将静态资源上传到 CDN。

## 🔄 更新升级

### 更新代码

```bash
# 拉取最新代码
git pull

# 重新构建并启动
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### 数据库迁移

如果数据库结构变更，系统会自动执行迁移脚本。

## 📝 常见问题

### Q: 如何重置管理员密码？

A: 直接修改数据库：

```bash
docker-compose exec backend python -c "
from src.user_manager import get_user_manager
um = get_user_manager()
um.change_password_by_username('admin', 'new_password')
"
```

### Q: 如何查看数据库内容？

A: 使用 SQLite 客户端：

```bash
docker-compose exec backend sqlite3 /app/data/inspection.db
```

### Q: 如何导出检测数据？

A: 使用 API 端点或直接在宿主机查找 Excel 文件：

```bash
# 通过 API
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/export/daily?format=excel

# 或直接复制文件
cp ./edge/data/export/*.xlsx ./backup/
```

### Q: 服务启动失败怎么办？

A: 按顺序检查：

1. 查看日志：`docker-compose logs`
2. 检查端口占用：`netstat -tlnp | grep :8000`
3. 检查磁盘空间：`df -h`
4. 检查内存：`free -h`
5. 重启 Docker：`sudo systemctl restart docker`

## 📞 技术支持

如遇到问题，请提供：

1. `docker-compose ps` 输出
2. 相关服务日志：`docker-compose logs backend frontend`
3. 系统信息：`uname -a`
4. Docker 版本：`docker --version`

---

**最后更新**: 2026-03-24  
**维护者**: AI视觉质检系统团队
