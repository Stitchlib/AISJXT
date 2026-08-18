"""AI 视觉质检系统 - 边缘计算后端核心包。

模块划分（清晰职责边界，便于维护与扩展）：
- models.py            数据契约（Pydantic Schema），模块间唯一数据交换格式
- config_manager.py    配置加载/持久化（单一配置源）
- database.py          检测结果持久化（SQLite，标准库实现，零额外依赖）
- websocket_manager.py 实时连接管理（由 detector/engine 推送，前端订阅）
- camera_manager.py    摄像头生命周期与状态管理
- detector.py          检测算法封装（YOLO 真实路径 + 优雅降级到标注仿真）
- inspection_engine.py 编排层：驱动检测循环、持久化、广播，模块间协作中枢
- routers/             HTTP 接口层，仅做协议转换，不含业务逻辑
"""
