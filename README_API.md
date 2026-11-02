# DUCKO 可选云端语音服务

先用内置音频试听，无需阿里云账号。此后端可选接入百炼，使用同一个 `qwen-audio-3.1-tts-flash` 模型完成情绪语音和声音复刻。

## Linux 启动

安装 Python 3.9 或更新版本。无需 pip、GPU、CUDA 或 Node。Ubuntu / Debian 若没有 Python：

```bash
sudo apt update
sudo apt install python3
```

在本目录打开终端：

```bash
python3 server.py
```

浏览器访问 `http://127.0.0.1:8765`。默认仅本机可访问，不开放跨域。录音请使用该 localhost 地址，不直接使用 `file://`。终端按 Ctrl+C 停止。

## 接入百炼

准备同一地域的 API Key 和业务空间 ID。需开通目标模型权限，实际合成按所选模型计费。不要在聊天、前端代码或共享文件中填写真实 Key。

在同一个 Linux 终端逐行执行，Key 输入时不回显：

```bash
read -rsp '百炼 API Key: ' DASHSCOPE_API_KEY; echo
export DASHSCOPE_API_KEY
read -rp '业务空间 ID: ' DASHSCOPE_WORKSPACE_ID
export DASHSCOPE_WORKSPACE_ID
export DASHSCOPE_REGION=cn-beijing
python3 server.py
```

新加坡地域可设置 `DASHSCOPE_REGION=ap-southeast-1`。业务空间 ID 与 Key 必须属于所选地域。`.env.example` 仅解释变量，不会被自动读取。

`configured: true` 只表示变量格式齐全，不代表权限、额度或音色已经在线验证。未配置时仍可播放内置音频；实时生成和复刻接口返回 503，不返回假音色。

## 前端接口

所有写入接口使用 `Content-Type: application/json`，与页面同源调用。错误统一为 `{"error":"中文说明","code":"错误代码"}`。

### GET /api/status

返回 `configured`、`tts_available`、`clone_available`、`online_verified: false`、`model`、`emotions`、`clone_formats`、`max_audio_bytes` 和 `message`。不包含 Key。

### POST /api/tts

```json
{"text":"你好，我是诺丁鸭。","language":"zh","emotion":"warm"}
```

- `text`：1–1000 字符。
- `language`：`zh` 或 `en`。
- `emotion`：`warm` 亲切、`happy` 活泼、`calm` 沉稳、`neutral` 自然。
- `voice_id`：可选；省略时使用系统音色 `longanhuan_v3.1`。复刻音色必须绑定上述模型。

成功返回 `{"audio_url":"/api/audio/随机ID.wav","model":"...","voice_id":"...","emotion":"warm","language":"zh","cached":true,"cache_ttl_seconds":1800}`。前端将 `audio_url` 直接赋给 audio 元素播放。音频与网页同源，Web Audio 分析器不依赖第三方存储的 CORS 配置。情绪由服务端模型的自然语言 `instruction` 控制，不是播放器变速伪装。

后端通过 HTTPS 下载百炼结果，只接受指定地域的 `dashscope-result-*` OSS 域名，不跟随重定向，下载请求不携带 API Key。单个 WAV 上限 16 MB；音频仅缓存在内存，最多 8 条、共 64 MB，最长 30 分钟，重启或容量满时可能提前失效。缓存不写磁盘，不向前端泄露云端签名链接。若下载失败，不会自动再次调用收费合成。

`GET /api/audio/随机ID.wav` 返回 `audio/wav`，支持单段 HTTP Range 以便拖动播放进度。缓存失效返回 410；内置演示音频不受缓存限制。

### POST /api/clone

```json
{"audio_base64":"仅Base64正文","mime_type":"audio/wav","language":"zh","reference_text":"可选录音转写"}
```

录音要求：本人或已获授权的声音；WAV 16-bit PCM / MP3 / M4A；建议 10–20 秒，至少 5 秒且不超过 60 秒；至少 16 kHz，最多 10 MB。仅 WAV 在本地检查采样率和时长，MP3/M4A 的详细参数由云端检查。浏览器默认 WebM 不能直接提交，须先转为 PCM16 WAV。不要仅修改扩展名。

当前官方 `voice-enrollment` 不使用转写文本，`reference_text` 接收但不保存、不发给云端，返回 `reference_text_used: false`。音频仅暂存内存，不写磁盘；执行复刻会将样本提交到百炼。

成功返回 `{"voice_id":"...","model":"...","ready":true,"status":"OK","reference_text_used":false,"message":"..."}`。若音色仍部署中，返回 HTTP 202 和 `ready:false`。必须保存返回的 voice_id，不要为重试重复创建音色。等待后调用 `GET /api/voice?voice_id=...`；`ready:true` 后把此 ID 传入 `/api/tts`。查询失败或未就绪不代表创建失败。服务不会自动重试创建请求。

## 已验证与限制

已对请求校验、同源限制、敏感文件访问限制、模型与音色绑定、云端参数、音频下载白名单、缓存过期及同源播放进行本地离线测试：

```bash
python3 -m unittest test_server.py
```

未使用真实 Key 调用线上合成或复刻。权限、模型可用性、合成音质及音色相似度仍需配置后实测。HTTP 服务仅用于本机演示，未实现公网部署认证、计费限额或多用户管理。

## 官方依据

核对日期：2026-11-02。

- [Qwen Audio TTS HTTP API](https://help.aliyun.com/zh/model-studio/qwen-audio-tts-http-api)
- [非实时合成与 instruction 控制](https://help.aliyun.com/zh/model-studio/non-realtime-tts-user-guide)
- [声音复刻 HTTP API](https://help.aliyun.com/zh/model-studio/voice-clone-design-http-api)
- [复刻流程与录音规格](https://help.aliyun.com/zh/model-studio/voice-cloning-user-guide)
