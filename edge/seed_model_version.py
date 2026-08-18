"""种子脚本：将已在 edge/model/ 下的真实权重注册为模型版本并激活。

运行（仓库根目录）：
    .venv/Scripts/python.exe edge/seed_model_version.py

效果：
- 在 model_versions 表插入（若已存在同名路径则复用）一条记录并置为 active；
- 将 config.json 的 model_path 指向该权重、enable_simulation=False 并落盘，
  使服务下次启动即进入真实推理模式（Detector.is_simulation=False）。

说明：通用 COCO 权重（yolov8n）用于验证真实推理流水线；生产环境应替换为
服装瑕疵专用权重，类别名才会是业务瑕疵类型。
"""
from __future__ import annotations

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config_manager import ConfigManager  # noqa: E402
from src.database import Database  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = (REPO_ROOT / "edge" / "model" / "yolov8n.pt").resolve()
DB_PATH = (REPO_ROOT / "data" / "inspection.db").resolve()  # 与 start-dev.bat 启动一致（CWD=仓库根）


def main() -> None:
    if not MODEL_PATH.exists():
        raise SystemExit(f"未找到权重文件: {MODEL_PATH}\n请先下载 yolov8n.pt 到 edge/model/")

    db = Database(str(DB_PATH))
    # 幂等：若已存在相同 file_path 的版本则复用
    existing = [v for v in db.list_model_versions() if Path(v["file_path"]).resolve() == MODEL_PATH]
    if existing:
        mv_id = existing[0]["id"]
        print(f"模型版本已存在，复用 id={mv_id} ({existing[0]['name']} {existing[0]['version']})")
    else:
        mv_id = db.create_model_version({
            "name": "YOLOv8n (COCO 通用基线)",
            "version": "8.3.0",
            "metric": 0.0,
            "description": "Ultralytics 官方 yolov8n 通用检测权重，验证真实推理流水线；生产需替换为服装瑕疵专用权重。",
            "file_path": str(MODEL_PATH),
            "active": True,
        })
        print(f"已注册模型版本 id={mv_id} -> {MODEL_PATH}")

    db.set_active_model_version(mv_id)

    cm = ConfigManager()
    cm.update(model_path=str(MODEL_PATH), enable_simulation=False)
    cfg = cm.get()
    print("config.model_path      =", cfg.model_path)
    print("config.enable_simulation =", cfg.enable_simulation)
    print("active model version   =", db.get_active_model_version()["id"])
    print("\n完成：服务启动后将加载真实权重进行推理（Detector.is_simulation=False）。")


if __name__ == "__main__":
    main()
