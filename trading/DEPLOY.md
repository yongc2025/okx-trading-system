# OKX 交易助手 - 安装部署指南

## 一、环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11 (64-bit) |
| Python | 3.10+ (如从源码运行) |
| 内存 | ≥ 4GB |
| 磁盘 | ≥ 500MB |
| 网络 | 需访问 api.okx.com |

---

## 二、安装方式

### 方式 A: 使用安装包 (推荐)

1. 获取 `OKX交易助手` 文件夹 (由 `build.bat` 打包生成)
2. 将文件夹放到任意目录 (建议 `C:\OKX交易助手\`)
3. 双击 `OKX交易助手.exe` 启动
4. 浏览器自动打开 `http://localhost:8888`

### 方式 B: 从源码运行

```bash
# 1. 克隆/复制项目
cd okx-trading-system

# 2. 运行安装脚本 (自动创建虚拟环境 + 安装依赖)
双击 install.bat

# 3. 启动
双击 start.bat
```

### 方式 C: 手动安装

```bash
# 1. 创建虚拟环境
python -m venv venv
venv\Scripts\activate

# 2. 安装依赖
pip install -r trading\requirements.txt

# 3. 设置环境变量
set PYTHONPATH=%cd%

# 4. 启动
python trading\run.py
```

---

## 三、首次使用

### 3.1 设置本地密码

首次启动后，系统会要求设置本地启动密码：
- 此密码用于加密存储你的 OKX API Key
- 密码仅保存在本地，不会上传任何服务器
- **请牢记密码，忘记后无法恢复已保存的 API Key**

### 3.2 配置 OKX API

1. 登录 [OKX 官网](https://www.okx.com) → API 管理 → 创建 API Key
2. 权限设置:
   - ✅ 读取 (必须)
   - ✅ 交易 (必须)
   - ❌ 提现 (不要勾选)
3. 将 API Key / Secret Key / Passphrase 填入交易助手
4. 如需测试，勾选「模拟盘」

### 3.3 连接验证

点击「连接」后，系统会自动:
- 验证 API Key 有效性
- 获取账户余额
- 建立 WebSocket 实时连接
- 保存凭证 (加密存储到本地 SQLite)

---

## 四、打包为安装包

### 4.1 使用 PyInstaller

```bash
# 安装 PyInstaller
pip install pyinstaller

# 方式一: 使用 bat 脚本
双击 build.bat

# 方式二: 使用 spec 文件 (更精细控制)
pyinstaller build.spec
```

### 4.2 打包输出

```
dist/
└── OKX交易助手/
    ├── OKX交易助手.exe      # 主程序
    ├── trading/
    │   ├── templates/       # 前端页面
    │   ├── static/          # 静态资源
    │   ├── db/              # 数据库 (运行时生成)
    │   └── logs/            # 日志 (运行时生成)
    ├── _internal/           # PyInstaller 依赖
    ├── README.md
    └── requirements.txt
```

### 4.3 制作安装程序 (可选)

如需制作标准 Windows 安装程序 (.exe)，可使用:

- **Inno Setup** (免费): https://jrsoftware.org/isinfo.php
- **NSIS** (免费): https://nsis.sourceforge.io/

Inno Setup 示例脚本:

```ini
[Setup]
AppName=OKX交易助手
AppVersion=1.0.0
DefaultDirName={autopf}\OKX交易助手
DefaultGroupName=OKX交易助手
OutputDir=installer
OutputBaseFilename=OKX交易助手_Setup

[Files]
Source: "dist\OKX交易助手\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\OKX交易助手"; Filename: "{app}\OKX交易助手.exe"
Name: "{group}\卸载"; Filename: "{uninstallexe}"
Name: "{commondesktop}\OKX交易助手"; Filename: "{app}\OKX交易助手.exe"

[Run]
Filename: "{app}\OKX交易助手.exe"; Description: "启动 OKX交易助手"; Flags: postinstall nowait
```

---

## 五、目录结构

```
OKX交易助手/
├── OKX交易助手.exe          # 主程序
├── trading/
│   ├── db/
│   │   ├── trading.db       # SQLite 数据库
│   │   └── .auth.json       # 密码哈希 (首次运行生成)
│   └── logs/
│       └── trading.log      # 运行日志 (按天滚动)
├── README.md
└── requirements.txt
```

---

## 六、常见问题

### Q: 启动后浏览器没有自动打开?
A: 手动访问 `http://localhost:8888`

### Q: 提示 "端口被占用"?
A: 修改启动命令指定端口: `python trading\run.py 8889`，然后访问 `http://localhost:8889`

### Q: 忘记本地密码?
A: 删除 `trading\db\.auth.json` 文件，重新启动后需重新设置密码并重新配置 API Key

### Q: 连接 OKX 失败?
A: 检查:
1. API Key 是否正确 (注意不要有多余空格)
2. API Key 权限是否包含「读取」和「交易」
3. 是否需要使用「模拟盘」
4. 网络是否能访问 `api.okx.com`

### Q: WebSocket 频繁断开?
A: 正常现象，系统会自动重连 (最大间隔 5 秒)。如持续断开，检查网络稳定性

### Q: 数据库文件在哪里?
A: `trading\db\trading.db`，可用 [DB Browser for SQLite](https://sqlitebrowser.org/) 查看

---

## 七、安全建议

1. **不要**将 API Key 的提现权限打开
2. **设置** OKX API 的 IP 白名单 (仅允许本机 IP)
3. **定期**检查 API Key 使用情况
4. **不要**将 `trading.db` 和 `.auth.json` 文件分享给他人
5. **建议**在 OKX 中设置子账户并限制子账户权限

---

## 八、卸载

1. 关闭程序
2. 删除整个安装目录
3. (可选) 删除用户数据: `%APPDATA%\OKX交易助手\`
