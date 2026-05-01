import asyncio
import httpx
import hmac
import hashlib
import base64
import time
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.append(str(Path(__file__).resolve().parent.parent))

from trading.config import PROXY_URL, OKX_REST_BASE, OKX_REST_DEMO

async def test_okx_connectivity(api_key, secret, passphrase, is_demo=False):
    print("=" * 50)
    print(f"开始测试 OKX 连通性 (环境: {'模拟盘' if is_demo else '实盘'})")
    print(f"当前代理设置: {PROXY_URL}")
    print("=" * 50)

    base_url = OKX_REST_DEMO if is_demo else OKX_REST_BASE
    path = "/api/v5/account/balance"
    method = "GET"
    
    # OKX 要求的时间格式是 ISO 8601，带 T 和 Z，例如 2020-12-08T09:08:49.070Z
    # 并且必须是 UTC 时间
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    
    # 生成签名
    message = timestamp + method + path
    mac = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    )
    signature = base64.b64encode(mac.digest()).decode("ascii")

    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }
    
    if is_demo:
        headers["x-simulated-trading"] = "1"

    try:
        print(f"正在发送请求到: {base_url}{path} ...")
        async with httpx.AsyncClient(proxy=PROXY_URL, timeout=10.0) as client:
            resp = await client.get(f"{base_url}{path}", headers=headers)
            
            print(f"HTTP 状态码: {resp.status_code}")
            data = resp.json()
            
            if resp.status_code == 200 and data.get("code") == "0":
                print("✅ [成功] 能够成功连接 OKX 并获取余额数据！")
            else:
                code = data.get("code")
                msg = data.get("msg", "未知错误")
                print(f"❌ [失败] OKX 返回错误码: {code}")
                print(f"错误信息: {msg}")
                
                # 针对性提示
                if code == "50101":
                     print("\n💡 提示: API Key 与环境不匹配。")
                     print("   - 如果您拿的是实盘 Key，刚才测试时选了 '模拟盘'，请切换。")
                     print("   - 如果您在模拟交易界面申请的 Key，请确保测试时选了 '模拟盘'。")
                elif code == "50105":
                     print("\n💡 提示: Passphrase (API 密码) 错误。")
                elif code == "50100":
                     print("\n💡 提示: 签名错误。通常是 Secret Key 填错了。")

    except Exception as e:
        print(f"❌ [异常] 请求过程中发生错误: {e}")
        if "10054" in str(e) or "64" in str(e) or "All connection attempts failed" in str(e):
            print("\n💡 提示: 网络连接被拒绝。这通常意味着您的 VPN/代理没开，或者端口 10809 不正确。")

if __name__ == "__main__":
    # 请用户在这里填入信息或通过命令行参数传入
    # 这里我们定义一个简单的交互式输入
    print("请输入您的 OKX API 信息进行测试：")
    ak = input("API Key: ").strip()
    sk = input("Secret Key: ").strip()
    pp = input("Passphrase: ").strip()
    demo_input = input("是否为模拟盘? (y/n): ").strip().lower()
    is_demo = demo_input == 'y'

    asyncio.run(test_okx_connectivity(ak, sk, pp, is_demo))
