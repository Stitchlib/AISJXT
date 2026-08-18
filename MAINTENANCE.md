# AI视觉质检系统 - 运维手册

## 📋 目录

1. [日常运维](#日常运维)
2. [监控与告警](#监控与告警)
3. [数据备份与恢复](#数据备份与恢复)
4. [性能优化](#性能优化)
5. [故障排查](#故障排查)
6. [系统升级](#系统升级)
7. [安全加固](#安全加固)

---

## 🔧 日常运维

### 服务状态检查

#### Docker 环境

```bash
# 查看所有容器状态
docker-compose ps

# 查看详细信息
docker inspect aibc-backend
docker inspect aibc-frontend

# 检查服务健康状态
curl http://localhost:8000/api/v1/health
curl http://localhost/health
```

#### 本地环境

```bash
# 检查后端进程
ps aux | grep python | grep main.py

# 检查端口占用
netstat -tlnp | grep 8000
netstat -tlnp | grep 5173

# 测试 API
curl http://localhost:8000/api/v1/health
```

### 日志管理

#### 查看日志

```bash
# Docker 环境
# 实时查看所有服务日志
docker-compose logs -f

# 查看特定服务最近 100 行日志
docker-compose logs --tail=100 backend
docker-compose logs --tail=100 frontend

# 按时间查看
docker-compose logs --since="2026-03-24 10:00:00" backend
docker-compose logs --until="2026-03-24 12:00:00" backend

# 本地环境
tail -f edge/logs/app.log
tail -f frontend/logs/*.log
```

#### 日志级别调整

编辑 `edge/config.yaml`：

```yaml
logging:
  level: INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
  rotation: "10 MB"
  retention: "30 days"
```

### 资源监控

#### Docker 容器资源

```bash
# 实时查看资源使用
docker stats aibc-backend aibc-frontend

# 查看容器详细信息
docker stats --no-stream

# 查看磁盘使用
docker system df
```

#### 系统资源

```bash
# CPU 和内存
top
htop

# 磁盘使用
df -h
du -sh ./edge/data
du -sh ./edge/logs

# 网络流量
iftop
nethogs
```

---

## 📊 监控与告警

### 系统健康监控

#### 通过 API 监控

```bash
# 后端健康检查
curl http://localhost:8000/api/v1/health

# 设备状态
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/device-status

# 数据库状态
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/database/status
```

#### 监控脚本示例

创建 `monitor.sh`：

```bash
#!/bin/bash

# 检查后端服务
if ! curl -s http://localhost:8000/api/v1/health | grep -q "ok"; then
    echo "❌ 后端服务异常"
    # 发送邮件告警
    echo "AI 质检系统后端服务异常" | mail -s "告警：后端服务宕机" admin@example.com
fi

# 检查前端服务
if ! curl -s http://localhost/health > /dev/null; then
    echo "❌ 前端服务异常"
    echo "AI 质检系统前端服务异常" | mail -s "告警：前端服务宕机" admin@example.com
fi

# 检查磁盘空间
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 90 ]; then
    echo "⚠️ 磁盘空间不足：${DISK_USAGE}%"
    echo "磁盘空间使用率：${DISK_USAGE}%" | mail -s "警告：磁盘空间不足" admin@example.com
fi

# 检查内存使用
MEM_USAGE=$(free | grep Mem | awk '{printf("%.0f", $3/$2*100)}')
if [ $MEM_USAGE -gt 90 ]; then
    echo "⚠️ 内存使用率过高：${MEM_USAGE}%"
    echo "内存使用率：${MEM_USAGE}%" | mail -s "警告：内存使用率过高" admin@example.com
fi
```

设置定时任务：

```bash
# 编辑 crontab
crontab -e

# 添加每 5 分钟检查一次
*/5 * * * * /path/to/monitor.sh
```

---

## 💾 数据备份与恢复

### 数据备份

#### 自动备份脚本

创建 `backup.sh`：

```bash
#!/bin/bash

BACKUP_DIR="/backup/aibc"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$BACKUP_DIR/backup_$DATE"

# 创建备份目录
mkdir -p $BACKUP_PATH

# 备份数据库
cp -r ./edge/data $BACKUP_PATH/

# 备份配置文件
cp -r ./edge/config $BACKUP_PATH/

# 备份日志（最近 7 天）
find ./edge/logs -name "*.log" -mtime -7 -exec cp {} $BACKUP_PATH/logs/ \;

# 压缩备份
cd $BACKUP_DIR
tar -czf backup_$DATE.tar.gz backup_$DATE
rm -rf backup_$DATE

# 删除 30 天前的备份
find $BACKUP_DIR -name "backup_*.tar.gz" -mtime +30 -delete

echo "✅ 备份完成：$BACKUP_PATH"
```

#### Docker 环境备份

```bash
# 停止服务
docker-compose down

# 备份数据卷
docker run --rm \
  -v aibc_data:/data/source \
  -v $(pwd)/backup:/data/backup \
  alpine tar czf /data/backup/data_$(date +%Y%m%d).tar.gz -C /data/source .

# 启动服务
docker-compose up -d
```

### 数据恢复

#### 从备份恢复

```bash
# 停止服务
docker-compose down

# 解压备份
tar -xzf backup_20260324_120000.tar.gz

# 恢复数据
cp -r backup_20260324_120000/data/* ./edge/data/

# 修复权限
chown -R $(id -u):$(id -g) ./edge/data

# 重启服务
docker-compose up -d
```

#### 数据库恢复

```bash
# 停止后端
docker-compose stop backend

# 恢复 SQLite 数据库
cp ./edge/data/inspection.db.backup ./edge/data/inspection.db

# 重启后端
docker-compose start backend
```

---

## ⚡ 性能优化

### 数据库优化

#### 定期清理旧数据

创建 `cleanup_database.py`：

```python
import sqlite3
from datetime import datetime, timedelta

db_path = 'edge/data/inspection.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 删除 30 天前的检测结果
thirty_days_ago = datetime.now() - timedelta(days=30)
cursor.execute(
    "DELETE FROM detection_results WHERE timestamp < ?",
    (thirty_days_ago.strftime('%Y-%m-%d %H:%M:%S'),)
)

# 删除孤立的缺陷记录
cursor.execute("""
    DELETE FROM defect_details 
    WHERE result_id NOT IN (SELECT id FROM detection_results)
""")

conn.commit()
vacuum_size = cursor.execute("PRAGMA freelist_count").fetchone()[0]
print(f"已清理数据，释放空间：{vacuum_size * 4096 / 1024 / 1024:.2f} MB")

conn.close()
```

#### 添加索引

```sql
-- 为常用查询字段添加索引
CREATE INDEX IF NOT EXISTS idx_detection_timestamp ON detection_results(timestamp);
CREATE INDEX IF NOT EXISTS idx_detection_status ON detection_results(status);
CREATE INDEX IF NOT EXISTS idx_detection_device ON detection_results(device_id);
CREATE INDEX IF NOT EXISTS idx_defect_type ON defect_details(defect_type);
```

### Redis 缓存优化

#### 配置 Redis

编辑 `docker-compose.yml`：

```yaml
redis:
  image: redis:7-alpine
  command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
  volumes:
    - redis-data:/data
```

#### 使用缓存

在代码中添加缓存装饰器：

```python
from functools import lru_cache
import time

@lru_cache(maxsize=100)
def get_detection_statistics(date_str):
    # 耗时查询结果缓存
    return db.query(...)

# 带过期时间的缓存
class TimedCache:
    def __init__(self, ttl_seconds=300):
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get(self, key):
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return value
        return None
    
    def set(self, key, value):
        self.cache[key] = (value, time.time())
```

### Nginx 优化

#### Gzip 压缩

已在 `nginx.conf` 中配置：

```nginx
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_types text/plain text/css application/json application/javascript;
gzip_comp_level 6;
```

#### 静态资源缓存

```nginx
# 版本化的静态资源缓存 1 年
location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}

# HTML 文件不缓存
location ~* \.html$ {
    expires -1;
    add_header Cache-Control "no-cache, no-store, must-revalidate";
}
```

---

## 🔍 故障排查

### 常见问题及解决方案

#### 1. 后端服务无法启动

**症状**：
- 容器不断重启
- 端口 8000 无法访问

**排查步骤**：

```bash
# 1. 查看详细日志
docker-compose logs backend

# 2. 检查配置文件
docker-compose exec backend cat /app/config/config.yaml

# 3. 检查数据库连接
docker-compose exec backend python -c "
import sqlite3
try:
    conn = sqlite3.connect('/app/data/inspection.db')
    print('✅ 数据库连接成功')
except Exception as e:
    print(f'❌ 数据库连接失败：{e}')
"

# 4. 检查端口占用
docker-compose exec backend netstat -tlnp | grep 8000
```

**常见原因**：
- 配置文件错误
- 数据库锁定
- 端口被占用
- 依赖缺失

**解决方案**：
```bash
# 修复配置文件
docker-compose exec backend vi /app/config/config.yaml

# 修复数据库权限
docker-compose down
sudo chown -R $(id -u):$(id -g) edge/data
docker-compose up -d

# 更换端口
# 修改 docker-compose.yml 中的端口映射
ports:
  - "8001:8000"  # 使用 8001 端口
```

#### 2. 前端页面空白

**症状**：
- 访问 http://localhost 显示空白
- 浏览器控制台报错

**排查步骤**：

```bash
# 1. 检查容器状态
docker-compose ps

# 2. 查看前端日志
docker-compose logs frontend

# 3. 检查 Nginx 配置
docker-compose exec frontend nginx -t

# 4. 测试后端连接
docker-compose exec frontend wget -qO- http://backend:8000/api/v1/health
```

**常见原因**：
- 构建失败
- Nginx 配置错误
- 后端服务不可用
- CORS 配置问题

**解决方案**：
```bash
# 重新构建前端
docker-compose build frontend
docker-compose up -d frontend

# 检查 CORS 配置
# 确保 edge/config.yaml 中配置了正确的 CORS 域名
cors:
  enabled: true
  origins:
    - "http://localhost"
    - "http://localhost:5173"
```

#### 3. 邮件发送失败

**症状**：
- 告警邮件无法发送
- 日志显示 SMTP 连接失败

**排查步骤**：

```bash
# 1. 检查邮件配置
cat edge/config/email_config.yaml

# 2. 测试 SMTP 连接
docker-compose exec backend python -c "
from src.email_notifier import get_email_notifier
notifier = get_email_notifier()
success = notifier.test_connection()
print(f'SMTP 测试：{\"成功\" if success else \"失败\"}')
"

# 3. 查看邮件日志
docker-compose logs backend | grep -i "email\|smtp"
```

**常见原因**：
- SMTP 配置错误
- 邮箱授权码失效
- 网络连接问题
- 防火墙阻止

**解决方案**：
```bash
# 修正邮件配置
vi edge/config/email_config.yaml

# QQ 邮箱示例：
enabled: true
smtp_server: smtp.qq.com
smtp_port: 465
use_tls: true
username: your_email@qq.com
password: your_auth_code  # 不是邮箱密码，是 SMTP 授权码

# 测试网络连通性
docker-compose exec backend ping smtp.qq.com
```

#### 4. WebSocket 连接断开

**症状**：
- 前端显示"连接已断开"
- 实时数据不更新

**排查步骤**：

```bash
# 1. 检查 WebSocket 管理器
docker-compose logs backend | grep -i "websocket"

# 2. 查看连接数
curl -H "Authorization: Bearer TOKEN" \
  http://localhost:8000/api/v1/websocket/stats

# 3. 检查 Nginx WebSocket 配置
docker-compose exec frontend cat /etc/nginx/conf.d/default.conf | grep -A 10 "Upgrade"
```

**解决方案**：
```nginx
# 确保 Nginx 配置包含 WebSocket 支持
location /api/ {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection 'upgrade';
    proxy_read_timeout 86400;
}
```

#### 5. 数据库锁定

**症状**：
- 写入操作失败
- 错误信息包含 "database is locked"

**解决方案**：

```bash
# 1. 停止后端服务
docker-compose stop backend

# 2. 查找并删除 WAL 文件
rm -f edge/data/inspection.db-wal
rm -f edge/data/inspection.db-shm

# 3. 修复权限
chown -R $(id -u):$(id -g) edge/data

# 4. 启用 WAL 模式（可选，提高并发性能）
docker-compose exec backend sqlite3 /app/data/inspection.db "PRAGMA journal_mode=WAL;"

# 5. 重启后端
docker-compose start backend
```

---

## 🔄 系统升级

### 版本升级流程

#### 1. 备份当前版本

```bash
# 备份数据和配置
./backup.sh

# 记录当前版本号
docker-compose exec backend python -c "
import json
with open('/app/config/config.yaml') as f:
    import yaml
    config = yaml.safe_load(f)
    print(f"当前版本：{config.get('version', 'unknown')}")
"
```

#### 2. 拉取新代码

```bash
# 进入项目目录
cd /opt/aibc

# 拉取最新代码
git pull origin main

# 查看变更
git log --oneline -10
```

#### 3. 更新 Docker 镜像

```bash
# 停止服务
docker-compose down

# 重新构建镜像
docker-compose build --no-cache

# 或者拉取最新镜像（如果使用预构建镜像）
docker-compose pull
```

#### 4. 数据库迁移

```bash
# 检查是否有数据库迁移脚本
ls -la migrations/

# 执行迁移
docker-compose exec backend python migrate.py
```

#### 5. 启动并验证

```bash
# 启动服务
docker-compose up -d

# 等待服务就绪
sleep 10

# 验证版本
curl http://localhost:8000/api/v1/health | jq '.version'

# 运行测试
python validate-all-features.py
```

### 回滚流程

```bash
# 1. 停止当前服务
docker-compose down

# 2. 恢复备份
./restore.sh backup_20260324_120000

# 3. 回滚代码
git checkout <previous-version-tag>

# 4. 重新构建
docker-compose build

# 5. 启动服务
docker-compose up -d
```

---

## 🔒 安全加固

### 定期安全检查清单

- [ ] 检查系统补丁更新
- [ ] 检查依赖包安全漏洞
- [ ] 审查用户账户和权限
- [ ] 检查防火墙规则
- [ ] 审计日志文件
- [ ] 验证备份完整性
- [ ] 更新 SSL 证书（如使用）

### Python 依赖安全检查

```bash
# 检查已知漏洞
docker-compose exec backend pip-audit

# 或手动检查
docker-compose exec backend pip list --outdated

# 更新依赖（谨慎操作）
docker-compose exec backend pip install --upgrade -r requirements.txt
```

### 前端依赖安全检查

```bash
# 检查漏洞
cd frontend
npm audit

# 自动修复
npm audit fix

# 强制修复（可能破坏兼容性）
npm audit fix --force
```

### 防火墙配置

```bash
# Ubuntu UFW 示例
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS（如配置）
sudo ufw allow 22/tcp    # SSH
sudo ufw enable

# 查看状态
sudo ufw status verbose
```

### SSL/HTTPS 配置（推荐生产环境）

使用 Nginx Proxy Manager 简化配置：

1. 安装 Nginx Proxy Manager
2. 添加 Proxy Host：
   - Domain: your-domain.com
   - Forward IP: 服务器 IP
   - Forward Port: 80
3. 申请 SSL 证书（Let's Encrypt）
4. 强制 HTTPS 重定向

---

## 📞 技术支持

### 获取帮助

- **官方文档**: PROJECT_COMPLETION_REPORT.md
- **快速指南**: QUICK_START.md
- **部署手册**: DEPLOYMENT.md
- **API 文档**: http://localhost:8000/api/v1/docs

### 提交问题

请提供以下信息：

1. 系统信息（操作系统、版本）
2. Docker 版本（如使用 Docker）
3. 相关日志输出
4. 错误截图或复现步骤
5. 已尝试的解决方案

---

**最后更新**: 2026-03-24  
**版本**: v2.0.0  
**维护团队**: AI视觉质检系统团队
