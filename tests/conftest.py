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

# 基于真实配置生成临时配置，仅替换数据库路径（保留摄像头等设置）
ORIG = EDGE / "config" / "config.json"
data = json.loads(ORIG.read_text(encoding="utf-8")) if ORIG.exists() else {}
data["db_path"] = DB_PATH
CFG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

cm_mod.ConfigManager._resolve_path = staticmethod(lambda: str(CFG_PATH))

# 模型权重上传目录重定向到临时目录，避免测试向真实的 edge/model 写入
# （沙箱会拦截对 edge/model 的写入，且真实权重不应被测试占位文件污染）。
import src.routers.model_versions as _mv_mod  # noqa: E402

_MV_DIR = _TMP / "models"
_MV_DIR.mkdir(parents=True, exist_ok=True)
_mv_mod.MODEL_DIR = _MV_DIR
