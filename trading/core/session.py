"""
OKX 交易助手 - 本地登录与会话管理
- 首次启动: 设置本地密码 → 加密存储 API Key
- 后续启动: 输入密码解锁 → 派生加密密钥 → 加载凭证 → 自动连接
"""
import hashlib
import os
import json
import time
from pathlib import Path
from typing import Optional

from trading.config import DB_DIR
from trading.core.encryption import derive_key, encrypt, decrypt
from trading.core.logger import log

# 本地密码哈希存储路径
AUTH_FILE = DB_DIR / ".auth.json"


class SessionManager:
    """
    本地会话管理器
    - 密码设置 / 验证
    - 会话状态 (已锁定 / 已解锁)
    - 自动连接触发
    """

    def __init__(self, db=None):
        self._unlocked = False
        self._password: Optional[str] = None
        self._unlock_time: Optional[float] = None
        self._db = db  # 可选注入，用于凭证重加密

    @property
    def is_unlocked(self) -> bool:
        return self._unlocked

    @property
    def password(self) -> Optional[str]:
        return self._password if self._unlocked else None

    @property
    def is_first_run(self) -> bool:
        """是否首次运行 (未设置过密码)"""
        return not AUTH_FILE.exists()

    # ----------------------------------------------------------
    # 密码管理
    # ----------------------------------------------------------
    def setup_password(self, password: str) -> dict:
        """
        首次设置本地密码
        - 对密码做 SHA-256 哈希存储 (非明文)
        - 生成随机盐用于后续 PBKDF2 密钥派生
        """
        if AUTH_FILE.exists():
            return {"error": "密码已存在，如需重置请先清除"}

        salt = os.urandom(16).hex()
        pw_hash = hashlib.sha256((password + salt).encode()).hexdigest()

        auth_data = {
            "pw_hash": pw_hash,
            "salt": salt,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTH_FILE.write_text(json.dumps(auth_data))

        self._password = password
        self._unlocked = True
        self._unlock_time = time.time()

        log.info("本地密码设置成功")
        return {"status": "ok"}

    def verify_password(self, password: str) -> dict:
        """
        验证密码并解锁会话
        """
        if not AUTH_FILE.exists():
            return {"error": "未设置密码，请先注册"}

        auth_data = json.loads(AUTH_FILE.read_text())
        salt = auth_data["salt"]
        expected = auth_data["pw_hash"]
        actual = hashlib.sha256((password + salt).encode()).hexdigest()

        if actual != expected:
            log.warning("密码验证失败")
            return {"error": "密码错误"}

        self._password = password
        self._unlocked = True
        self._unlock_time = time.time()

        log.info("会话解锁成功")
        return {"status": "ok", "unlock_time": self._unlock_time}

    def lock(self):
        """锁定会话"""
        self._unlocked = False
        self._password = None
        self._unlock_time = None
        log.info("会话已锁定")

    def change_password(self, old_password: str, new_password: str, db=None) -> dict:
        """修改本地密码 (需要重新加密所有 API 凭证)"""
        if not self._unlocked:
            return {"error": "会话未解锁"}

        # 验证旧密码
        auth_data = json.loads(AUTH_FILE.read_text())
        salt = auth_data["salt"]
        expected = auth_data["pw_hash"]
        actual = hashlib.sha256((old_password + salt).encode()).hexdigest()
        if actual != expected:
            return {"error": "旧密码错误"}

        # 重新加密 API 凭证
        from trading.data.database import Database
        from trading.core.encryption import encrypt as enc, decrypt as dec
        _db = db or self._db or Database()
        should_close = db is None and self._db is None

        rows = _db.fetchall("SELECT id, api_key, secret, passphrase FROM api_credentials")
        for row in rows:
            try:
                ak = dec(row["api_key"], old_password)
                sk = dec(row["secret"], old_password)
                pp = dec(row["passphrase"], old_password)
            except Exception:
                continue
            with _db.transaction():
                _db.execute(
                    "UPDATE api_credentials SET api_key=?, secret=?, passphrase=?, updated_at=datetime('now') WHERE id=?",
                    (enc(ak, new_password), enc(sk, new_password), enc(pp, new_password), row["id"]),
                )

        if should_close:
            _db.close()

        # 更新密码哈希
        new_salt = os.urandom(16).hex()
        new_hash = hashlib.sha256((new_password + new_salt).encode()).hexdigest()
        AUTH_FILE.write_text(json.dumps({
            "pw_hash": new_hash,
            "salt": new_salt,
            "created_at": auth_data.get("created_at", ""),
            "changed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }))

        self._password = new_password
        log.info("密码修改成功，API 凭证已重新加密")
        return {"status": "ok"}

    def reset(self) -> dict:
        """清除密码和所有凭证 (危险操作)"""
        if AUTH_FILE.exists():
            AUTH_FILE.unlink()
        self.lock()
        log.warning("密码和会话已重置")
        return {"status": "ok"}
