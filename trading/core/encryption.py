"""
OKX 交易助手 - AES-256 加密工具
"""
import os
import base64
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from trading.config import ENCRYPTION_ITERATIONS, ENCRYPTION_KEY_LENGTH, ENCRYPTION_SALT_LENGTH


def derive_key(password: str, salt: bytes) -> bytes:
    """从用户密码派生 AES-256 密钥 (PBKDF2)"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=ENCRYPTION_KEY_LENGTH,
        salt=salt,
        iterations=ENCRYPTION_ITERATIONS,
        backend=default_backend(),
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt(plaintext: str, password: str) -> str:
    """
    AES-256-CBC 加密
    返回: base64(salt + iv + ciphertext)
    """
    salt = os.urandom(ENCRYPTION_SALT_LENGTH)
    key = derive_key(password, salt)
    iv = os.urandom(16)

    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    return base64.b64encode(salt + iv + ciphertext).decode("ascii")


def decrypt(encrypted_b64: str, password: str) -> str:
    """
    AES-256-CBC 解密
    输入: base64(salt + iv + ciphertext)
    """
    raw = base64.b64decode(encrypted_b64)
    salt = raw[:ENCRYPTION_SALT_LENGTH]
    iv = raw[ENCRYPTION_SALT_LENGTH:ENCRYPTION_SALT_LENGTH + 16]
    ciphertext = raw[ENCRYPTION_SALT_LENGTH + 16:]

    key = derive_key(password, salt)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    return plaintext.decode("utf-8")
