# 语音识别使用说明

本项目支持浏览器识别与Python原生识别。默认模式下，页面优先使用已就绪的当前语言Python识别器；未安装时自动使用浏览器Vosk模型，也可在设置中选择浏览器识别。两条路径都不需要API Key，不把提问音频发给语音云服务。

识别只负责把录音转成文字。问答能力由页面的演示知识条目提供，不是Vosk在回答问题。

## 先使用浏览器识别

用支持麦克风、WebAssembly和Web Worker的现代浏览器打开HTTPS网站，点击说话，按提示加载模型并允许麦克风。这条路径不需要Python。首次读取中文模型约44 MB、英文约41 MB，识别程序约5.8 MB；准备完成后可复用模型继续提问。

在Linux上运行完整项目时，只需要先启动网页服务，无需先安装Vosk：

```bash
cd ~/Downloads/DUCKO语音Demo
python3 server.py
```

按实际位置修改第一行路径，保持终端运行，打开 `http://127.0.0.1:8765`。Windows启动方法见 `README_WINDOWS.md`。

保持 `browser-asr.js`、`vendor/`、`models-browser/` 和音频资源目录完整。双击 `file://` HTML不启用浏览器识别，应从HTTPS或localhost打开。单文件演示可播放内嵌音频，但不等于内含了识别模型。

模型与网页加载后，识别可继续离线运行；离线重新打开网页取决于缓存，本演示没有完整PWA离线安装承诺。7寸屏只是显示设备，运行速度与内存由主机决定，需实机验证。详见 `README_BROWSER_ASR.md`。

## 可选 安装 Linux 原生识别器

只有希望在本机Python进程执行识别时才需要本节。公开仓库不包含 `.asr-vendor` 或原生 `models/` 目录；首次安装联网下载依赖与模型，完成后识别不联网，不保存原始录音。

准备：Linux x86_64 或 ARM64、Python 3.9 或更新版本、可用麦克风和扬声器。为演示预留至少 1 GB 可用内存和 300 MB 磁盘空间；这是部署预留值，不是实机性能承诺。暂不支持 ARMv6 设备。

1. 解压完整演示包。在该目录打开终端。
2. Ubuntu / Debian 没有 Python 虚拟环境工具时安装：

   ```bash
   sudo apt update
   sudo apt install python3 python3-venv
   ```

3. 安装中文识别。命令会创建本目录的 `.venv`，安装官方 PyPI 的 `vosk==0.3.45`，从 Vosk 官方网站下载约 42 MB 的中文小模型：

   ```bash
   sh setup_asr.sh zh
   ```

4. 如需英文识别，再安装约 40 MB 的英文小模型：

   ```bash
   .venv/bin/python setup_asr.py en
   ```

没有原生英文模型时，仍可通过浏览器英文模型识别，也可输入英文文字。浏览器使用 `models-browser/` 中的tar.gz文件，Python使用 `models/` 中的解压目录，两者不能直接互换路径。

## 原生识别每次启动

```bash
cd ~/Downloads/DUCKO语音Demo
.venv/bin/python server.py
```

如果解压位置不同，修改第一行路径。保持终端运行，浏览器打开 `http://127.0.0.1:8765`。也可运行 `sh start.sh`，该脚本会优先使用本目录的 `.venv/bin/python`。

点击页面的说话按钮，允许这个本机页面使用麦克风。说完后结束录音，页面会显示识别文字并自动回答；识别错了可在输入框修改后重新发送。页面每轮最多录音 15 秒，停顿后也会自动提交；接口上限为 20 秒。连续对话期间，播报时暂停采集，避免机器人把自己的回答再次识别成提问。

首次提问需要加载模型，通常比之后慢。中文小模型适合演示，会误识别专有名词和嘈杂环境中的讲话；不能把它的结果当作可靠的导航或安全指令。

## 分别检查两种识别器

浏览器识别：查看页面设置中的当前引擎、模型加载阶段和就绪状态。模型就绪不代表麦克风已经授权，仍要实际讲话检查电平、识别文字和播报结果。

Python原生识别：以下状态接口只检查本机Python，不描述浏览器模型。

在浏览器打开 `http://127.0.0.1:8765/api/status`：

- `asr_available: true` 表示依赖和至少一个模型已找到。
- `asr_languages: ["zh"]` 表示仅安装了中文；有英文时包含 `"en"`。
- `asr_model_loaded` 在第一次成功加载后包含相应语言。
- 若模型加载失败，后续状态会移除该语言并显示说明；修复后重启服务。

未安装原生识别器时，`asr_available: false`是正常状态，不代表网页不能语音交互。HTTPS静态网站没有Python的 `/api/status` 接口。原生状态显示可用也不代表已经通过麦克风测试，仍需在机器人实际音频设备和噪声环境下验证。

## 常见问题

**浏览器模型加载失败**：检查网络、项目文件是否完整、模型URL是否可访问及可用内存。按页面提示重试；仍不可用时用文字输入，不会伪造识别结果。

**页面提示本地服务未连接**：检查终端是否还在运行，网址是否为上述地址。若端口占用，执行 `.venv/bin/python server.py --port 8766`，浏览器也改为 8766。

**原生依赖已安装但显示未就绪**：确认运行的是 `.venv/bin/python`。中文目录应为 `models/vosk-model-small-cn-0.22/am/final.mdl`，不能多嵌套一层同名目录。

**下载失败**：检查是否可访问 Vosk 官方网站后重试。也可从官方模型页手动下载并解压到 `models`。不要仅创建空模型文件夹。

**需要从自定义位置读取模型**：在启动前设置 `VOSK_MODEL_ZH` 或 `VOSK_MODEL_EN` 为解压后的模型目录。Linux 支持 UTF-8 路径；Windows 原生库可能无法读取中文绝对路径，建议在本演示目录内启动，或将模型放到英文路径。

**听不准**：先用耳机或降低扬声器音量，靠近麦克风，用短句提问。查看并修改文字后提交。后续再评估阵列麦克风、回声消除、更准确的识别模型和术语适配。

**网页不能录音**：使用 localhost 或 HTTPS，检查浏览器权限和系统输入设备。服务器不需要 `sounddevice`、PyAudio 或麦克风驱动库；音频由浏览器采集。

## Python 原生识别接口

本节只适用于本机服务。浏览器WebAssembly识别直接调用 `DuckoBrowserASR`，不发送 `/api/asr` 请求。

`POST /api/asr`，与页面同源调用：

```json
{"audio_base64":"纯 Base64 正文","mime_type":"audio/wav","language":"zh"}
```

仅接受单声道、16 kHz、16-bit PCM WAV，时长 0.25–20 秒。前端须在生成 WAV 前降采样，不能只改文件头。WebM、MP3 或 48 kHz WAV 不会被自动转换。API 不会调用云端识别。

成功示例：

```json
{"text":"介绍一下宁波诺丁汉大学","language":"zh","engine":"vosk","offline":true,"duration_seconds":3.5}
```

空文本代表没有识别到内容，前端应提示重说，不能伪造问题。一次只处理一条识别请求；忙时返回 429，未安装返回 503，格式错误返回 400。错误体为 `{"error":"说明","code":"错误代码"}`。处理的音频和转写不写入文件，也不记入访问日志。

## 后续替换

原生路线可保持 `/api/asr` 的输入输出不变，替换其他本地模型；浏览器路线需保持 `DuckoBrowserASR` 适配接口，详见 `README_BROWSER_ASR.md`。开放问答还需知识检索与回答生成；可打断播报还需流式识别、回声消除和会话状态管理，不能只更换识别模型就认为这些能力已经实现。

## 官方资料

核对日期：2026-11-02。

- [Vosk 安装与平台支持](https://alphacephei.com/vosk/install)
- [官方模型列表及许可证](https://alphacephei.com/vosk/models)
- [官方 Python WAV 识别示例](https://github.com/alphacep/vosk-api/blob/master/python/example/test_simple.py)
- [Vosk 官方 PyPI 软件包](https://pypi.org/project/vosk/)
