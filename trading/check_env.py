"""
OKX 交易助手 - 启动前校验
检查环境、依赖、目录权限等
"""
import sys
import os
import shutil
import importlib
from pathlib import Path


def check_python_version() -> bool:
    v = sys.version_info
    ok = v.major == 3 and v.minor >= 10
    status = "✅" if ok else "❌"
    print(f"  {status} Python {v.major}.{v.minor}.{v.micro} (需要 3.10+)")
    return ok


def check_dependencies() -> bool:
    required = [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("httpx", "httpx"),
        ("websockets", "websockets"),
        ("cryptography", "cryptography"),
        ("jinja2", "jinja2"),
    ]
    all_ok = True
    for name, module in required:
        try:
            mod = importlib.import_module(module)
            ver = getattr(mod, "__version__", "?")
            print(f"  ✅ {name} {ver}")
        except ImportError:
            print(f"  ❌ {name} 未安装")
            all_ok = False
    return all_ok


def check_directories() -> bool:
    base = Path(__file__).resolve().parent.parent
    dirs = [
        base / "trading" / "db",
        base / "trading" / "logs",
        base / "trading" / "templates",
        base / "trading" / "static",
    ]
    all_ok = True
    for d in dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
            # 测试写权限
            test_file = d / ".write_test"
            test_file.write_text("ok")
            test_file.unlink()
            print(f"  ✅ {d.name}/ 可写")
        except Exception as e:
            print(f"  ❌ {d.name}/ 不可写: {e}")
            all_ok = False
    return all_ok


def check_disk_space() -> bool:
    total, used, free = shutil.disk_usage("/")
    free_mb = free // (1024 * 1024)
    ok = free_mb > 100
    status = "✅" if ok else "⚠️"
    print(f"  {status} 可用磁盘空间: {free_mb}MB")
    return ok


def check_port(port: int = 8888) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", port))
        s.close()
        print(f"  ✅ 端口 {port} 可用")
        return True
    except OSError:
        print(f"  ⚠️  端口 {port} 已被占用 (可使用其他端口: python trading/run.py <端口>)")
        return True  # 非阻断性问题


def run_all_checks() -> bool:
    print("=" * 50)
    print("OKX 交易助手 - 环境检查")
    print("=" * 50)
    print()

    print("[1/5] Python 版本:")
    py_ok = check_python_version()
    print()

    print("[2/5] 依赖包:")
    dep_ok = check_dependencies()
    print()

    print("[3/5] 目录权限:")
    dir_ok = check_directories()
    print()

    print("[4/5] 磁盘空间:")
    disk_ok = check_disk_space()
    print()

    print("[5/5] 端口检查:")
    port_ok = check_port()
    print()

    all_ok = py_ok and dep_ok and dir_ok and disk_ok
    if all_ok:
        print("🎉 环境检查通过，可以启动交易助手")
    else:
        print("⚠️  存在问题，请修复后重试")

    return all_ok


if __name__ == "__main__":
    ok = run_all_checks()
    sys.exit(0 if ok else 1)
