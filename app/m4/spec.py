"""授信测算口径说明：读取 formula_spec.json，并为每次重算生成可审计的版本戳。

本模块不参与数值计算。calc.py 的结果不变；这里只描述口径，并把版本写入方案结果。
"""
import hashlib
import json
from pathlib import Path

_DIR = Path(__file__).resolve().parent
SPEC_PATH = _DIR / "formula_spec.json"
CALC_PATH = _DIR / "calc.py"

_POLICIES = ("null_and_alert", "zero", "skip")


def load_spec():
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if not spec.get("version") or not isinstance(spec.get("columns"), list):
        raise ValueError("formula_spec.json 缺少 version 或 columns")
    return spec


def calc_module_hash():
    """calc.py 文件内容的 SHA-256。口径文件与代码漂移时，结果里的哈希会变。"""
    return hashlib.sha256(CALC_PATH.read_bytes()).hexdigest()


def result_meta(param, dataset_id):
    spec = load_spec()
    return {
        "formula_spec_version": spec["version"],
        "param_id": param["id"],
        "param_version": param["version"],
        "dataset_id": dataset_id,
        "calc_module_hash": calc_module_hash(),
    }


def validate_spec(spec=None):
    """供测试与启动自检：列说明字段齐全，缺失策略只使用约定的三种。"""
    spec = spec or load_spec()
    ids = []
    for col in spec["columns"]:
        for k in ("id", "expr_human", "inputs", "missing_policy", "source"):
            if k not in col or col[k] in (None, "", []):
                raise ValueError(f"口径列 {col.get('id')} 缺少 {k}")
        if col["missing_policy"] not in _POLICIES:
            raise ValueError(f"口径列 {col['id']} 的 missing_policy 无效")
        if not isinstance(col["inputs"], list):
            raise ValueError(f"口径列 {col['id']} 的 inputs 须为列表")
        ids.append(col["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("口径列 id 重复")
    return spec
