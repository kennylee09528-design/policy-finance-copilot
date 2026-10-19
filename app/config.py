"""全局配置：路径与环境变量。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PH_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("PH_DB_PATH", DATA_DIR / "workbench.db"))
EXPORT_DIR = DATA_DIR / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = BASE_DIR / "static"
SAMPLES_DIR = BASE_DIR / "samples"
M4_SAMPLE = SAMPLES_DIR / "m4" / "附件2：2026年各合作担保机构授信额度计算表（示例）.xlsx"
QINGSHI_TEMPLATE = SAMPLES_DIR / "m4" / "qingshi_template.docx"
M5_SAMPLE_DIR = SAMPLES_DIR / "m5"
M5_SUMMARY_SAMPLE = M5_SAMPLE_DIR / "1.业务额度使用情况 - 截止2026年9月19日v1.xlsx"
