"""测试隔离：把应用使用的配置与数据库重定向到临时目录，避免污染仓库。

conftest 在 test 模块 import main 之前执行：
- 将 ConfigManager 的路径解析重定向到一个临时 config.json；
- 该临时配置基于真实 edge/config/config.json（保留摄像头等设置），
  仅把 db_path 改为临时库，从而让 TestClient 生命周期里的 Database 落到临时库；
- 单元测试自行创建的 Database(tmp_path/...) 不受影响。
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))

import src.config_manager as cm_mod  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture
def client():
    """共享的应用客户端：使用 conftest 注入的临时配置/数据库，保证测试隔离。"""
    with TestClient(app) as c:
        yield c

_TMP = Path(tempfile.mkdtemp(prefix="aiqc_test_"))
CFG_PATH = _TMP / "config" / "config.json"
CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
DB_PATH = str(_TMP / "inspection.db")

# 基于真实配置生成临时配置，仅替换数据库路径（保留摄像头等设置）。
# 真实配置不存在时（CI / 新机器：edge/config/config.json 被 gitignore），
# 注入测试种子配置：cam_001/cam_002 仿真摄像头。
# 测试套件隐含依赖这两个摄像头（camera 列表非空、WS 启停、stage2c 双仿真并发、
# cam_001 视频流/ROI）——此前该依赖仅由开发者本机配置满足，是 CI 上
# 10 个用例失败的根因（cameras=[]、未知摄像头 cam_001、active 回退到
# discovery 用例注册的 cam_net_192_168_1_50）。
_SEED_CAMERAS = {
    "cameras": [
        {"id": "cam_001", "name": "主摄像头", "type": "simulated", "source": "0", "enabled": True},
        {"id": "cam_002", "name": "副摄像头", "type": "simulated", "source": "1", "enabled": True},
    ],
    "active_camera_id": "cam_001",
}
ORIG = EDGE / "config" / "config.json"
data = json.loads(ORIG.read_text(encoding="utf-8")) if ORIG.exists() else dict(_SEED_CAMERAS)
data["db_path"] = DB_PATH
CFG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

cm_mod.ConfigManager._resolve_path = staticmethod(lambda: str(CFG_PATH))

# 模型权重上传目录重定向到临时目录，避免测试向真实的 edge/model 写入
# （沙箱会拦截对 edge/model 的写入，且真实权重不应被测试占位文件污染）。
import src.routers.model_versions as _mv_mod  # noqa: E402

_MV_DIR = _TMP / "models"
_MV_DIR.mkdir(parents=True, exist_ok=True)
_mv_mod.MODEL_DIR = _MV_DIR
