"""API Key 加密存储：Fernet 对称加密。密钥来自环境变量 PH_SECRET_KEY，或首次启动自动生成 data/secret.key（权限 600）。"""
import os

from cryptography.fernet import Fernet

from ..config import DATA_DIR

_f = None


def _fernet():
    global _f
    if _f is None:
        key = os.environ.get("PH_SECRET_KEY")
        if not key:
            p = DATA_DIR / "secret.key"
            if not p.exists():
                p.write_bytes(Fernet.generate_key())
                os.chmod(p, 0o600)
            key = p.read_bytes().strip()
        _f = Fernet(key if isinstance(key, bytes) else key.encode())
    return _f


def encrypt(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode() if s else ""


def decrypt(s: str) -> str:
    return _fernet().decrypt(s.encode()).decode() if s else ""


def mask(plain: str) -> str:
    if not plain:
        return ""
    return (plain[:3] + "****" + plain[-4:]) if len(plain) > 10 else "****"
