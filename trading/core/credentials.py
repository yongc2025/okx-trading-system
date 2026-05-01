"""
OKX 交易助手 - API 凭证管理
"""
from trading.core.encryption import encrypt, decrypt
from trading.data.database import Database


class CredentialManager:
    """API Key 加密存储与读取"""

    def __init__(self, db: Database, password: str):
        self._db = db
        self._password = password

    def save(self, api_key: str, secret: str, passphrase: str,
             label: str = "default", is_demo: bool = False):
        """加密并保存 API 凭证"""
        with self._db.transaction():
            self._db.execute(
                """INSERT OR REPLACE INTO api_credentials
                   (label, api_key, secret, passphrase, is_demo, updated_at)
                   VALUES(?,?,?,?,?,datetime('now'))""",
                (
                    label,
                    encrypt(api_key, self._password),
                    encrypt(secret, self._password),
                    encrypt(passphrase, self._password),
                    int(is_demo),
                ),
            )

    def load(self, label: str = "default") -> dict | None:
        """读取并解密 API 凭证"""
        row = self._db.fetchone(
            "SELECT * FROM api_credentials WHERE label=?", (label,)
        )
        if row is None:
            return None
        return {
            "api_key": decrypt(row["api_key"], self._password),
            "secret": decrypt(row["secret"], self._password),
            "passphrase": decrypt(row["passphrase"], self._password),
            "is_demo": bool(row["is_demo"]),
        }

    def delete(self, label: str = "default"):
        with self._db.transaction():
            self._db.execute("DELETE FROM api_credentials WHERE label=?", (label,))

    def list_labels(self) -> list[dict]:
        return self._db.fetchall(
            "SELECT label, is_demo, created_at FROM api_credentials ORDER BY id"
        )
