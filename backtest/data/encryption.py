"""
回测系统 - AES-256 加密工具
用于加密存储 API Key / Secret / Passphrase
"""
import os
import base64
from pathlib import Path

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from backtest.config import (
    ENCRYPTION_KEY_FILE,
    ENCRYPTION_SALT_LENGTH,
    ENCRYPTION_ITERATIONS,
    ENCRYPTION_KEY_LENGTH,
)


def _get_or_create_key() -> str:
    """获取或创建本地加密密钥（存储在 data/.key 文件）"""
    key_file = Path(ENCRYPTION_KEY_FILE)
    if key_file.exists():
        return key_file.read_text().strip()

    # 生成随机密钥
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key)
    # 设置文件权限为仅所有者可读写
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return key


def _derive_key(password: str, salt: bytes) -> bytes:
    """从密码派生 AES-256 密钥 (PBKDF2)"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=ENCRYPTION_KEY_LENGTH,
        salt=salt,
        iterations=ENCRYPTION_ITERATIONS,
        backend=default_backend(),
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt(plaintext: str) -> str:
    """
    AES-256-CBC 加密（使用本地密钥文件）
    返回: base64(salt + iv + ciphertext)
    """
    password = _get_or_create_key()
    salt = os.urandom(ENCRYPTION_SALT_LENGTH)
    key = _derive_key(password, salt)
    iv = os.urandom(16)

    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    return base64.b64encode(salt + iv + ciphertext).decode("ascii")


def decrypt(encrypted_b64: str) -> str:
    """
    AES-256-CBC 解密（使用本地密钥文件）
    输入: base64(salt + iv + ciphertext)
    """
    password = _get_or_create_key()
    raw = base64.b64decode(encrypted_b64)
    salt = raw[:ENCRYPTION_SALT_LENGTH]
    iv = raw[ENCRYPTION_SALT_LENGTH:ENCRYPTION_SALT_LENGTH + 16]
    ciphertext = raw[ENCRYPTION_SALT_LENGTH + 16:]

    key = _derive_key(password, salt)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    return plaintext.decode("utf-8")