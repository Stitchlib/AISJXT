# AI 视觉质检系统 - 快速启动指南

## 🚀 5 分钟快速开始

### 方式一：Docker 部署（推荐）⭐

**前提条件**：
- Docker Desktop 已安装
- Docker Compose 已安装

**步骤**：

1. **一键部署**
   ```bash
   # Windows 用户
   deploy-docker.bat
   
   # Linux/Mac 用户
   docker-compose up -d
   ```

2. **验证部署**
   ```bash
   docker-compose ps
   ```

3. **访问应用**
   - 前端：http://localhost
   - 后端 API: http://localhost:8000/api/v1
   - API 文档：http://localhost:8000/api/v1/docs

4. **默认账户**
   - 用户名：`admin`
   - 密码：`admin123`
   - ⚠️ 首次登录后必须修改！

---

### 方式二：本地运行

**前提条件**：
- Python 3.9+
- Node.js 18+

#### 后端启动

```bash
# 1. 进入 edge 目录
cd edge

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动后端服务
python main.py
```

后端将在 `http://localhost:8000` 启动

#### 前端启动

```bash
# 1. 进入 frontend 目录
cd frontend

# 2. 安装依赖
npm install

# 3. 启动开发服务器
npm run dev
```

前端将在 `http://localhost:5173` 启动

---

## 🔧 配置选项

### 邮件通知配置

```bash
# 1. 复制配置示例
cp edge/config/email_config.yaml.example edge/config/email_config.yaml

# 2. 编辑配置文件
# 填入你的邮箱信息
```

**常见邮箱 SMTP 配置**：

| 邮箱服务商 | SMTP 服务器 | 端口 | 加密方式 |
|-----------|------------|------|---------|
| QQ 邮箱 | smtp.qq.com | 465 | SSL/TLS |
| 163 邮箱 | smtp.163.com | 465 | SSL/TLS |
| Gmail | smtp.gmail.com | 587 | TLS |
| Outlook | smtp.office365.com | 587 | TLS |

### 环境变量（可选）

创建 `.env` 文件：

```bash
# 数据库路径
DATABASE_URL=sqlite:///edge/data/inspection.db

# JWT 密钥（生产环境必须修改！）
JWT_SECRET_KEY=your-secret-key-here

# 日志级别
LOG_LEVEL=INFO
```

---

## 📝 常用操作

### 查看日志

```bash
# Docker 方式
docker-compose logs -f

# 查看特定服务
docker-compose logs backend
docker-compose logs frontend
```

### 停止服务

```bash
# Docker 方式
docker-compose down

# 本地运行
# 按 Ctrl+C 停止服务
```

### 重启服务

```bash
# Docker 方式
docker-compose restart

# 重启单个服务
docker-compose restart backend
```

### 数据备份

```bash
# 使用部署工具
deploy-docker.bat -> 选项 [9]

# 或手动备份
cp -r edge/data ./backup/data_$(date +%Y%m%d)
```

---

## 🎯 功能验证

### 运行完整测试

```bash
# 验证所有新增功能
python validate-all-features.py
```

### 测试新功能

```bash
# Windows
test-new-features.bat

# 或直接运行
python tests/test_new_features.py
```

---

## 📱 PWA 安装（可选）

### Chrome/Edge浏览器

1. 访问 http://localhost
2. 点击右上角菜单 → 安装"AI 质检"
3. 或点击地址栏右侧的安装图标

### 桌面快捷方式

安装后可在桌面找到应用图标，双击即可启动。

---

## 🔐 安全提醒

1. **修改默认密码**
   - 首次登录后立即修改 admin 密码
   - 使用强密码（至少 8 位）

2. **更改 JWT 密钥**
   ```bash
   # 在生产环境变量中设置
   export JWT_SECRET_KEY=your-production-secret
   ```

3. **启用 HTTPS**
   - 生产环境建议配置 SSL 证书
   - 使用 Nginx Proxy Manager 简化配置

---

## 🆘 故障排查

### 后端无法启动

```bash
# 检查端口占用
netstat -ano | findstr :8000

# 查看日志
docker-compose logs backend
```

### 前端无法访问

```bash
# 检查构建
cd frontend
npm run build

# 查看日志
docker-compose logs frontend
```

### 数据库锁定

```bash
# 停止后端
docker-compose stop backend

# 修复权限
sudo chown -R $(id -u):$(id -g) edge/data

# 重启后端
docker-compose start backend
```

### 邮件发送失败

```bash
# 检查配置
cat edge/config/email_config.yaml

# 测试连接
python -c "from src.email_notifier import get_email_notifier; n=get_email_notifier(); print(n.test_connection())"
```

---

## 📞 获取帮助

- **API 文档**: http://localhost:8000/api/v1/docs
- **部署指南**: DEPLOYMENT.md
- **功能总结**: docs/功能增强完成总结.md

---

## ✅ 验证清单

部署完成后，请确认：

- [ ] 后端服务正常运行（端口 8000）
- [ ] 前端服务正常运行（端口 80）
- [ ] 可以访问登录页面
- [ ] 可以使用 admin 账户登录
- [ ] 数据库文件已创建（edge/data/inspection.db）
- [ ] 日志文件正常生成（edge/logs/）

---

**最后更新**: 2026-03-24  
**版本**: v2.0.0
