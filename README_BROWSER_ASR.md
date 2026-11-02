# 静态网页语音识别

这条路径用于 GitHub Pages 等静态网站：浏览器获取麦克风音频，在浏览器自己的 Web Worker 中运行 Vosk 模型。访客不用安装 Python，也不用填写 API Key。提问录音不发给语音云服务。

## 使用条件

- 使用支持麦克风、WebAssembly、Web Worker 的浏览器，建议先在桌面 Chrome、Edge 或 Firefox 验证。
- 网站必须是 HTTPS；本机开发可用 `http://localhost` 或 `http://127.0.0.1`。双击 `file://` 文件不启用浏览器模型。
- 首次使用中文需要从本网站读取约 44 MB 模型；英文约 41 MB。识别程序约 5.8 MB，仅在需要时加载。
- 模型运行还需要内存。不要把下载文件大小当作运行内存；7 寸屏对应的 Linux 主机仍须实际测试。
- 网页和模型加载完成后，识别可在断网状态下继续进行。重新打开离线网页是否成功还取决于浏览器缓存；本演示没有承诺完整的离线 PWA 安装能力。

## 网站要保留的文件

```text
index.html
browser-asr.js
vendor/vosk-browser/dist/vosk.js
vendor/vosk-browser/LICENSE-2.0.txt
vendor/vosk-browser/PROVENANCE.md
models-browser/vosk-model-small-cn-0.22-browser-v2.tar.gz.part01.bin 至 part07.bin
models-browser/vosk-model-small-en-us-0.15-browser-v2.tar.gz.part01.bin 至 part07.bin
models-browser/manifest.json
models-browser/LICENSE-2.0.txt
```

保留原目录结构。路径根据 `browser-asr.js` 的所在目录计算，支持 `https://账号.github.io/项目名/`，不能把模型路径改成站点根目录下的 `/models-browser/...`。

`vosk.js` 已包含 WASM 与 Worker，不需要额外访问 CDN。模型由已下载的官方 Vosk 模型转换为 tar.gz，再分为每片最多 6 MiB 的文件；压缩包顶层目录为 `model/`，模型内容没有改动。静态网站必须完整上传清单所列的所有分片，不需要上传原始大 tar.gz；原始包仍保留在开发目录。

当前使用 `browser-v2` 模型包：每个父目录都有明确的 0755 权限目录项，文件权限为 0644。旧包没有目录项，Vosk 内置解压器创建的父目录会留下 000 权限，导致解压后的文件系统同步报错。新文件名隔离旧模型缓存；清单请求也带版本参数并要求重新验证缓存。开发目录保留旧包用于排查，发布只采用当前清单列出的分片。

浏览器按顺序读取分片，校验每片和合并后压缩包的 SHA-256，再交给 Vosk。下载进度显示实际收到的字节数。完整压缩包可缓存在本站的 Cache API；缓存不可用时仍可直接加载。Vosk 的解压缓存使用稳定的模型 URL，不会因为临时 Blob 地址每次不同而生成重复的 IndexedDB 模型目录。

官方库文件没有修改。适配器只在创建 Vosk Worker 的同步过程中临时包装 Worker 构造器，随即恢复；包装 Worker 仅把指定模型 URL 的 fetch 映射到已校验的内存 Blob，然后导入官方 Worker。模型加载完或取消时撤销临时 Blob URL。本机 Python 静态服务需允许读取 `models-browser/` 下的 `.bin` 文件。

## 前端接入

在页面加载 `browser-asr.js`，并在用户点击说话按钮后执行准备流程：

```js
const controller = new AbortController();
await DuckoBrowserASR.prepare('zh', progress => {
  statusElement.textContent = progress.message;
}, controller.signal);

// pcm 是已经采集并转换为 16 kHz 单声道的 Float32Array。
const result = await DuckoBrowserASR.transcribe(pcm, 'zh', controller.signal);
questionInput.value = result.text;
```

接口约定：

| 方法 | 返回或行为 |
|---|---|
| `supported()` | 当前页面协议与浏览器是否具备必要能力；不代表已获得麦克风授权。 |
| `languages` | `['zh', 'en']`。 |
| `prepare(language, onProgress, signal)` | 加载程序与模型；完成后返回语言、引擎及 `offline:true`。 |
| `transcribe(pcm, language, signal)` | 输入 16 kHz 单声道 Float32Array，时长 0.25–20 秒；返回 `text`、`language`、`engine`、`offline`、`duration_ms`。 |
| `cancel()` | 立即结束当前加载或识别 Promise。识别中的 Worker 会被终止，下一次重新准备模型。 |
| `dispose()` | 释放模型和识别 Worker。 |
| `getStatus()` | 返回 `supported`、`ready`、`language`、`preparing`、`busy`、`engine`。 |

准备阶段包括 `loading-library`、`downloading-model`、`verifying-model`、`loading-model`、`ready`。其中下载阶段提供真实 `received` 和 `total` 字节数。程序加载限时 45 秒，下载及模型初始化分别限时 3 分钟，单次识别限时 45 秒。取消返回 `AbortError`。

一次只保留一个语言模型，切换识别语言会释放上一个模型。普通识别结束后保留模型，供后续提问复用。传入音频不会被写入本地存储；Vosk 自己可能把模型文件缓存到该站点的 IndexedDB。

## 与本机 Python 服务的关系

本机服务使用 Python Vosk；静态网站使用浏览器 Vosk。两者都可以执行实际识别。页面应显示当前使用哪一种，不应把浏览器兼容性检查当作识别已经就绪。

如果浏览器缺少能力、权限被拒绝、模型缺失或内存不足，应显示原因并保留文字输入，不应伪造“已识别”的文字。浏览器模型也不能生成新答案或模仿音色：识别后的文字仍要交给问答模块，播报由现有音频或另行配置的 TTS 完成。

## 来源

核对日期：2026 年 11 月 2 日。

- [Vosk Browser 项目](https://github.com/ccoreilly/vosk-browser)
- [实际调用的 Model 和 KaldiRecognizer 源码](https://github.com/ccoreilly/vosk-browser/blob/master/lib/src/model.ts)
- [官方 npm 包](https://www.npmjs.com/package/vosk-browser)
- [Vosk 官方模型及许可证](https://alphacephei.com/vosk/models)

库版本固定为 0.0.8，分发文件未修改，npm SHA-512 校验记录在 `vendor/vosk-browser/PROVENANCE.md`。中文与英文模型均为 Apache 2.0，文件大小和 SHA-256 在 `models-browser/manifest.json`。
