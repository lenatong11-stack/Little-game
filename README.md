# 视觉游戏自动化实操作业

本项目实现 Android 游戏视觉自动化，并提供老师查看的静态网页。Midscene Android Agent 读取实时截图、按自然语言定位游戏界面并执行动作；结束后调用视觉断言检查结果。ADB 任务运行记录和截图留存在本机。

网页默认填写《王者荣耀》的包名 `com.tencent.tmgp.sgame`。每次任务的操作由填写的自然语言决定。服务启动一次即可依次运行多个任务，每次运行分别保存记录与截图。

## 1. 环境要求

- Windows 10/11
- Python 3.7 或更高版本（网页服务只使用 Python 标准库）
- Node.js 18+，需包含 `npm`（Midscene SDK 运行环境）
- Android SDK Platform-Tools，ADB 已安装
- Android 手机开启 USB 调试并授权；小米设备还需打开“USB 调试（安全设置）”以允许模拟触控
- 一个 Midscene 支持的视觉模型服务 API Key

本机 Android Platform-Tools 位于 `D:\Android\platform-tools`。建议设置 `ANDROID_HOME=D:\Android`，并将 `%ANDROID_HOME%\platform-tools` 加入用户 `Path`。在新的 PowerShell 窗口运行 `adb devices`，确认手机状态为 `device`。

Node.js 安装后，在新 PowerShell 窗口运行 `node --version` 和 `npm --version`，两个命令都应返回版本号。ADB 需能运行 `adb devices` 并显示设备状态 `device`。

## 2. 安装 Midscene 与模型

在项目目录打开 PowerShell：

```powershell
cd midscene
npm install
Copy-Item .env.example .env
notepad .env
```

在 `.env` 中填写模型供应商提供的 API Key 和对应的模型名称、Base URL、Family。配置字段与可用模型见 [Midscene Android SDK 模型配置](https://www.midscenejs.com/get-started/android-sdk-api-key)。`.env` 只保存在本机，不能提交到仓库。

## 3. 设备执行端

另开一个 PowerShell 窗口，在项目根目录运行：

```powershell
python app.py
```

设备执行端在运行 Midscene 的电脑上启动。执行测试需要这台电脑连接已授权的 Android 手机。

## 4. 老师查看页面

给老师查看或上传的是 `teacher-site/` 下的只读测试结果页，不是项目介绍页。它不使用 `127.0.0.1`，也不请求本机 API。可直接打开 `teacher-site/index.html` 预览，或把整个目录上传到课程平台、GitHub Pages 或其他静态托管。测试任务仍由设备执行端控制；重新运行后需更新这份静态结果快照。

## 5. 创建和运行视觉任务

1. 确认网页设备栏显示手机序列号和 `device` 状态。
2. 填写应用包名 `com.tencent.tmgp.sgame`。
3. 给本次任务取名，填写自然语言步骤。可以写一段话，或者每行写一个操作，便于网页逐步记录。可选填一个截图上能观察到的最终验收条件。
4. 创建并运行。每个阶段完成后保存截图。若中途异常，任务停止并尝试保存现场截图，可从任务卡片复制日志。
5. 查看最后一张截图，核对本次任务的目标状态。出现账号授权、扫码、验证码等步骤时，按失败截图处理后再新建任务。

## 6. 项目结构与架构

- `app.py`：Python 标准库 HTTP 网页服务及任务 API，只监听本机地址。
- `adb_client.py`：ADB 设备发现、分辨率查询、启动应用、截图和底层设备调用。
- `runner.py`：异步逐步执行、保留日志、前后截图、错误步骤和最终状态。
- `midscene/visual_agent.mjs`：Midscene Android Agent，自然语言视觉操作与 `aiAssert`。
- `midscene/package.json`：Node 依赖声明。
- `midscene/.env.example`：模型配置示例，不含真实密钥。
- `templates/index.html`：设备选择、自然语言任务表单、日志/截图结果页。
- `学习记录.md`：需求分析、实现路径、AI 使用说明、实测台账。
- `架构说明.md`：网页、任务服务、ADB 设备控制和视觉模型之间的协作方式。
- `测试说明.md`：游戏选择、预期流程、失败复盘与实测台账。

执行链：网页表单 → Python API → 任务运行器 → Midscene Agent（读取屏幕、视觉定位、执行、断言）→ ADB 截图与设备信息 → 本地任务 JSON/截图 → 网页结果。

游戏画面由 Unity `SurfaceView` 绘制，UIAutomator 只能看到整个画布，拿不到具体控件树。因此任务依赖 Midscene 的截图理解与视觉定位，不依赖控件 ID 或固定点击坐标。视觉断言也可能误判，交付前需要人工复核截图。

## 7. 测试与提交

网页的“创建失败演示”触发受控的无效步骤，用于确认失败步骤、错误原因能否留档；它不会点击手机。正常流程请用真实设备完成至少三次，并保存每次日志和关键截图。作业还要求一段 3–5 分钟演示视频，需在本机实际操作录制。

当前交付包含源码、运行说明、架构与学习记录。由于模型 API Key 需要由使用者提供，三次真实视觉模型成功运行和演示视频应在配置密钥后完成；`学习记录.md` 的台账明确标注为待实测，不能用虚构记录替代。
