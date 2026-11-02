#!/usr/bin/env python3
"""DUCKO local demo server. Python 3.9+.

No credentials are needed to serve bundled demo assets. Cloud synthesis and
voice cloning are optional, and are never claimed to work without credentials.
See README_API.md for setup and the API contract.
Static/cloud endpoints use the standard library. Optional offline recognition
requires the Vosk package and local model files; see README_ASR.md.
"""
import argparse
import base64
import binascii
from collections import OrderedDict
import io
import importlib.util
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_AUDIO = 10 * 1024 * 1024
MAX_BODY = 15 * 1024 * 1024
MAX_GENERATED_AUDIO = 16 * 1024 * 1024
MAX_CACHE_BYTES = 64 * 1024 * 1024
AUDIO_CACHE_TTL = 30 * 60
MODEL = 'qwen-audio-3.1-tts-flash'
VOICE = 'longanhuan_v3.1'
EMOTIONS = {
    'warm': '用温暖、亲切的语气说话，语速适中，停顿自然，像校园里的友好向导。',
    'happy': '用活泼、开心、充满好奇的语气说话，语调有起伏，清晰自然，不要喊叫。',
    'calm': '用沉稳、平静、从容的语气讲解，语速稍慢，句尾落稳，吐字清晰。',
    'neutral': '自然清晰地说话，使用正常语速。',
}
MIME_TYPES = {'audio/wav': 'audio/wav', 'audio/x-wav': 'audio/wav',
              'audio/wave': 'audio/wav', 'audio/mpeg': 'audio/mpeg',
              'audio/mp3': 'audio/mpeg', 'audio/mp4': 'audio/mp4',
              'audio/x-m4a': 'audio/mp4', 'audio/m4a': 'audio/mp4'}

ASR_MODELS = {'zh': 'vosk-model-small-cn-0.22', 'en': 'vosk-model-small-en-us-0.15'}
MAX_ASR_SECONDS = 20


class APIError(Exception):
    def __init__(self, status, message, code='request_failed'):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward a model credential through a redirect."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LocalASR:
    """Local PCM recognition only. No upload, transcript log, or cloud fallback."""
    def __init__(self, environ=None):
        env = os.environ if environ is None else environ
        base = Path(__file__).resolve().parent / 'models'
        self.paths = {lang: Path(env.get('VOSK_MODEL_' + lang.upper(), str(base / name))).expanduser()
                      for lang, name in ASR_MODELS.items()}
        self.models = {}
        self.load_failures = set()
        self.model_lock = threading.Lock()
        self.recognition_slot = threading.BoundedSemaphore(1)

    def status(self):
        try:
            installed = importlib.util.find_spec('vosk') is not None
        except (ImportError, ValueError):
            installed = False
        languages = [lang for lang, path in self.paths.items()
                     if installed and (path / 'am' / 'final.mdl').is_file()
                     and (path / 'conf').is_dir() and lang not in self.load_failures]
        if not installed:
            message = '本地识别未安装。请按 README_ASR.md 运行安装步骤，再使用虚拟环境启动服务。'
        elif not languages:
            message = '本地识别模型缺失或加载失败。请安装模型，检查路径后重启服务。'
        else:
            message = '本地 Vosk 识别可用；首次提问会加载模型。录音不上传云端、不保存文件。'
        return {'asr_available': bool(languages), 'asr_languages': languages,
                'asr_engine': 'vosk', 'asr_offline': True,
                'asr_model_loaded': list(self.models), 'asr_message': message,
                'asr_format': 'PCM16 mono WAV 16000 Hz', 'asr_max_seconds': MAX_ASR_SECONDS}

    def load_model(self, language):
        with self.model_lock:
            if language not in self.models:
                if language not in self.status()['asr_languages']:
                    raise APIError(503, '此语言的本地识别尚未就绪。请按 README_ASR.md 安装模型，或先使用文字提问。', 'asr_not_ready')
                try:
                    from vosk import Model, SetLogLevel
                    SetLogLevel(-1)
                    model_path = str(self.paths[language])
                    # The Windows native library may not open a UTF-8 absolute
                    # path. A relative ASCII path works when started in this folder.
                    if os.name == 'nt':
                        relative = os.path.relpath(self.paths[language])
                        if relative.isascii():
                            model_path = relative
                    self.models[language] = Model(model_path)
                except Exception:
                    self.load_failures.add(language)
                    raise APIError(503, '无法加载本地识别模型，请检查安装、模型路径和可用内存后重启。', 'asr_model_failed') from None
            return self.models[language]

    def transcribe(self, body):
        language = body.get('language', 'zh')
        if language not in ('zh', 'en'):
            raise APIError(400, '识别语言只支持 zh 或 en。', 'invalid_language')
        if body.get('mime_type', 'audio/wav') not in ('audio/wav', 'audio/x-wav', 'audio/wave'):
            raise APIError(400, '本地识别需要 16kHz 单声道 PCM16 WAV，不支持 WebM 或 MP3。', 'asr_invalid_format')
        encoded = body.get('audio_base64')
        if not isinstance(encoded, str) or not encoded or len(encoded) > 1400000:
            raise APIError(400, '识别音频为空或过长，最多录制 20 秒。', 'asr_invalid_audio')
        try:
            raw = base64.b64decode(encoded, validate=True)
            with wave.open(io.BytesIO(raw), 'rb') as audio:
                if (audio.getnchannels() != 1 or audio.getsampwidth() != 2
                        or audio.getframerate() != 16000 or audio.getcomptype() != 'NONE'):
                    raise ValueError('wrong PCM format')
                frames = audio.getnframes()
                duration = frames / 16000
                if not 0.25 <= duration <= MAX_ASR_SECONDS:
                    raise ValueError('wrong duration')
                pcm = audio.readframes(frames)
                if len(pcm) != frames * 2:
                    raise ValueError('truncated WAV')
        except (ValueError, binascii.Error, wave.Error, EOFError):
            raise APIError(400, '请提交完整的 16kHz 单声道 PCM16 WAV，时长 0.25 至 20 秒。', 'asr_invalid_audio') from None
        if not self.recognition_slot.acquire(blocking=False):
            raise APIError(429, '本地识别正在处理另一段语音，请稍后重试。', 'asr_busy')
        try:
            model = self.load_model(language)
            from vosk import KaldiRecognizer
            recognizer = KaldiRecognizer(model, 16000)
            pieces = []
            started = time.monotonic()
            for offset in range(0, len(pcm), 8000):
                if time.monotonic() - started > 45:
                    raise APIError(504, '本地识别耗时较长，请缩短提问，或检查设备负载。', 'asr_timeout')
                if recognizer.AcceptWaveform(pcm[offset:offset + 8000]):
                    pieces.append(json.loads(recognizer.Result()).get('text', ''))
            pieces.append(json.loads(recognizer.FinalResult()).get('text', ''))
            text = ' '.join(piece.strip() for piece in pieces if isinstance(piece, str) and piece.strip())
            if language == 'zh':
                text = re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])', '', text)
            return {'text': text, 'language': language, 'engine': 'vosk', 'offline': True,
                    'duration_seconds': round(duration, 3)}
        except APIError:
            raise
        except Exception:
            raise APIError(500, '本地识别失败，请重试或使用文字提问。', 'asr_failed') from None
        finally:
            self.recognition_slot.release()


class App:
    def __init__(self, environ=None):
        env = os.environ if environ is None else environ
        self.key = env.get('DASHSCOPE_API_KEY', '').strip()
        self.workspace = env.get('DASHSCOPE_WORKSPACE_ID', '').strip()
        self.region = env.get('DASHSCOPE_REGION', 'cn-beijing').strip()
        self.model = MODEL
        self.voice = VOICE
        self.valid_workspace = bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,99}', self.workspace))
        self.configured = bool(self.key and self.valid_workspace and self.region in ('cn-beijing', 'ap-southeast-1'))
        self.base = f'https://{self.workspace}.{self.region}.maas.aliyuncs.com/api/v1'
        self.opener = urllib.request.build_opener(NoRedirect())
        # Separate downloader: it never receives the model Authorization header.
        self.audio_opener = urllib.request.build_opener(NoRedirect())
        self.audio_cache = OrderedDict()
        self.cache_lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(2)
        self.asr = LocalASR(env)

    def require_cloud(self):
        if not self.configured:
            raise APIError(503, '云端语音未配置。内置样音仍可直接试听；实时合成及复刻需在本机配置百炼 API Key 和业务空间 ID。', 'cloud_not_configured')

    def status(self):
        return {
            'configured': self.configured,
            'tts_available': self.configured,
            'clone_available': self.configured,
            'online_verified': False,
            'model': self.model,
            'emotions': list(EMOTIONS),
            'clone_formats': ['audio/wav', 'audio/mpeg', 'audio/mp4'],
            'max_audio_bytes': MAX_AUDIO,
            'message': '云端参数已配置，权限及额度以实际调用结果为准。' if self.configured else '演示模式：播放内置样音。实时生成和声音复刻尚未接入。',
            **self.asr.status(),
        }

    def cloud(self, path, payload, timeout=30):
        self.require_cloud()
        request = urllib.request.Request(self.base + path,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Authorization': 'Bearer ' + self.key,
                     'Content-Type': 'application/json'}, method='POST')
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise APIError(502, '云端响应过大。', 'upstream_response_invalid')
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError('not an object')
                if data.get('code') and not isinstance(data.get('output'), dict):
                    raise APIError(502, '云端未返回音频或音色，请检查服务配置与账户额度。', 'upstream_rejected')
                return data
        except urllib.error.HTTPError as error:
            messages = {400: '云端拒绝参数或音频格式，请检查样本及模型要求。',
                        401: '百炼凭证无效，请在本机检查 API Key。',
                        403: '百炼权限不足，请检查业务空间、模型权限或账户状态。',
                        404: '未找到云端资源，请检查地域、业务空间和音色 ID。',
                        429: '云端请求受限，请稍后再试并检查账户额度。'}
            # Do not echo arbitrary upstream messages: they may contain secrets.
            raise APIError(502, messages.get(error.code, '云端服务暂时不可用，请稍后重试。'), 'upstream_http_' + str(error.code)) from None
        except (TimeoutError, socket.timeout):
            raise APIError(504, '云端响应超时，请稍后再试。', 'upstream_timeout') from None
        except (urllib.error.URLError, OSError):
            raise APIError(502, '无法连接百炼服务，请检查网络。', 'upstream_network_error') from None
        except (ValueError, UnicodeError):
            raise APIError(502, '云端响应格式不正确。', 'upstream_response_invalid') from None

    def check_voice(self, voice_id):
        if not isinstance(voice_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,256}', voice_id):
            raise APIError(400, '音色 ID 格式不正确。', 'invalid_voice')
        if voice_id != self.voice and not voice_id.startswith(self.model + '-'):
            raise APIError(400, '复刻音色必须绑定到当前 qwen-audio-3.1-tts-flash 模型。', 'voice_model_mismatch')
        return voice_id

    def tts(self, body):
        self.require_cloud()
        text = body.get('text', '')
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise APIError(400, '请输入 1 至 1000 个字符的讲解文本。', 'invalid_text')
        language = body.get('language', 'zh')
        emotion = body.get('emotion', 'warm')
        if language not in ('zh', 'en'):
            raise APIError(400, '请选择中文或英文。', 'invalid_language')
        if not isinstance(emotion, str) or emotion not in EMOTIONS:
            raise APIError(400, '请选择亲切、活泼、沉稳或自然语气。', 'invalid_emotion')
        voice = self.check_voice(body.get('voice_id') or self.voice)
        instruction = ('请使用普通话。' if language == 'zh' else 'Please speak English. ') + EMOTIONS[emotion]
        result = self.cloud('/services/audio/tts/SpeechSynthesizer', {
            'model': self.model, 'input': {'text': text.strip(), 'voice': voice,
            'instruction': instruction, 'format': 'wav', 'sample_rate': 24000}})
        output = result.get('output', {})
        audio = output.get('audio', {}) if isinstance(output, dict) else {}
        url = audio.get('url', '') if isinstance(audio, dict) else ''
        if not isinstance(url, str):
            raise APIError(502, '云端未返回可播放音频。', 'audio_missing')
        local_url = self.cache_audio(url)
        return {'audio_url': local_url, 'model': self.model, 'voice_id': voice,
                'emotion': emotion, 'language': language,
                'cached': True, 'cache_ttl_seconds': AUDIO_CACHE_TTL}

    def cache_audio(self, url):
        """Download only a model result from a scoped OSS host; serve it same-origin."""
        try:
            if not isinstance(url, str) or len(url) > 8192 or re.search(r'[\s\\\\\x00-\x1f]', url):
                raise ValueError('invalid URL')
            parsed = urllib.parse.urlsplit(url)
            # Model responses use dashscope-result-* buckets in the service regions.
            # Reject arbitrary OSS buckets, custom hosts, private/internal endpoints,
            # embedded credentials and custom ports. No redirects are followed.
            host_pattern = r'dashscope-result-[a-z0-9-]+\.oss-(?:cn-beijing|ap-southeast-1)\.aliyuncs\.com'
            if (parsed.scheme not in ('http', 'https') or parsed.username or parsed.password
                    or not re.fullmatch(host_pattern, parsed.hostname or '')
                    or parsed.port not in (None, 443 if parsed.scheme == 'https' else 80)
                    or parsed.fragment):
                raise ValueError('untrusted URL')
            # Official responses can contain http OSS URLs. Always fetch via TLS.
            safe_url = urllib.parse.urlunsplit(('https', parsed.hostname, parsed.path, parsed.query, ''))
        except ValueError:
            raise APIError(502, '云端音频地址不属于允许的百炼结果存储域名。', 'untrusted_audio_url') from None
        request = urllib.request.Request(safe_url, headers={'Accept': 'audio/wav'}, method='GET')
        try:
            deadline = time.monotonic() + 30
            chunks, length = [], 0
            with self.audio_opener.open(request, timeout=15) as response:
                while True:
                    chunk = response.read(min(65536, MAX_GENERATED_AUDIO + 1 - length))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    length += len(chunk)
                    if length > MAX_GENERATED_AUDIO:
                        raise APIError(502, '合成音频超过本机 16 MB 限制。', 'generated_audio_too_large')
                    if time.monotonic() > deadline:
                        raise APIError(504, '下载合成音频超时。', 'audio_download_timeout')
            raw = b''.join(chunks)
            if len(raw) < 44 or raw[:4] != b'RIFF' or raw[8:12] != b'WAVE':
                raise APIError(502, '云端下载结果不是有效的 WAV 音频。', 'invalid_generated_audio')
        except (TimeoutError, socket.timeout):
            raise APIError(504, '下载合成音频超时。', 'audio_download_timeout') from None
        except (urllib.error.URLError, OSError):
            raise APIError(502, '合成已完成，但音频下载失败。请检查网络后再操作。', 'audio_download_failed') from None
        token = secrets.token_hex(16) + '.wav'
        with self.cache_lock:
            self._purge_audio()
            while self.audio_cache and (len(self.audio_cache) >= 8 or
                    sum(len(entry[1]) for entry in self.audio_cache.values()) + len(raw) > MAX_CACHE_BYTES):
                self.audio_cache.popitem(last=False)
            self.audio_cache[token] = (time.monotonic() + AUDIO_CACHE_TTL, raw)
        return '/api/audio/' + token

    def _purge_audio(self):
        now = time.monotonic()
        for token, (expires, _) in list(self.audio_cache.items()):
            if expires <= now:
                del self.audio_cache[token]

    def get_audio(self, token):
        if not re.fullmatch(r'[a-f0-9]{32}\.wav', token):
            raise APIError(404, '音频不存在。', 'audio_not_found')
        with self.cache_lock:
            self._purge_audio()
            entry = self.audio_cache.get(token)
            if entry is None:
                raise APIError(410, '此音频缓存已失效，请重新生成。', 'audio_cache_expired')
            return entry[1]

    def validate_audio(self, body):
        mime = body.get('mime_type', '')
        if not isinstance(mime, str) or mime.split(';')[0].lower() not in MIME_TYPES:
            raise APIError(400, '复刻样本请使用 WAV、MP3 或 M4A；浏览器 WebM 录音需要先转为 PCM16 WAV。', 'unsupported_audio_format')
        mime = MIME_TYPES[mime.split(';')[0].lower()]
        encoded = body.get('audio_base64', '')
        if not isinstance(encoded, str) or not encoded or len(encoded) > 14 * 1024 * 1024:
            raise APIError(400, '音频为空或大于 10 MB。', 'invalid_audio')
        if encoded.startswith('data:'):
            raise APIError(400, 'audio_base64 只接受 Base64 正文，不含 Data URI 前缀。', 'invalid_audio')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise APIError(400, '音频编码无效。', 'invalid_audio') from None
        if not raw or len(raw) > MAX_AUDIO:
            raise APIError(400, '音频为空或大于 10 MB。', 'invalid_audio')
        if mime == 'audio/wav':
            try:
                with wave.open(io.BytesIO(raw), 'rb') as audio:
                    duration = audio.getnframes() / audio.getframerate()
                    if audio.getsampwidth() != 2 or audio.getframerate() < 16000 or audio.getnchannels() not in (1, 2):
                        raise APIError(400, 'WAV 需为 16-bit PCM、至少 16 kHz、单声道或双声道。', 'invalid_audio_spec')
                    if not 5 <= duration <= 60:
                        raise APIError(400, '录音需为 5 至 60 秒，建议 10 至 20 秒。', 'invalid_audio_duration')
            except (wave.Error, EOFError, ZeroDivisionError):
                raise APIError(400, '无法读取 WAV，请上传有效的 PCM16 WAV。', 'invalid_audio') from None
        elif mime == 'audio/mpeg' and not (raw.startswith(b'ID3') or (len(raw) > 1 and raw[0] == 255 and raw[1] & 0xe0 == 0xe0)):
            raise APIError(400, '文件内容不是有效的 MP3。', 'invalid_audio')
        elif mime == 'audio/mp4' and (len(raw) < 12 or raw[4:8] != b'ftyp'):
            raise APIError(400, '文件内容不是有效的 M4A。', 'invalid_audio')
        return 'data:' + mime + ';base64,' + encoded

    def query_voice(self, voice_id):
        self.require_cloud()
        voice_id = self.check_voice(voice_id)
        data = self.cloud('/services/audio/tts/customization',
            {'model': 'voice-enrollment', 'input': {'action': 'query_voice', 'voice_id': voice_id}}, timeout=5)
        output = data.get('output', {})
        status = output.get('status', 'UNKNOWN') if isinstance(output, dict) else 'UNKNOWN'
        # Avoid reflecting untrusted upstream content into the page.
        if status not in ('OK', 'DEPLOYING', 'UNDEPLOYED'):
            status = 'UNKNOWN'
        return {'voice_id': voice_id, 'model': self.model, 'ready': status == 'OK', 'status': status}

    def clone(self, body):
        self.require_cloud()
        sample = self.validate_audio(body)
        language = body.get('language', 'zh')
        if language not in ('zh', 'en'):
            raise APIError(400, '参考录音语言请选择中文或英文。', 'invalid_language')
        data = self.cloud('/services/audio/tts/customization', {
            'model': 'voice-enrollment', 'input': {
                'action': 'create_voice', 'target_model': self.model,
                'prefix': 'ducko', 'audio': sample,
                'language_hints': [language], 'max_prompt_audio_length': 20.0,
                'enable_preprocess': False}}, timeout=15)
        output = data.get('output', {})
        voice_id = output.get('voice_id') if isinstance(output, dict) else None
        if not isinstance(voice_id, str) or not voice_id.startswith(self.model + '-'):
            raise APIError(502, '云端未返回有效音色 ID。', 'voice_missing')
        status = {'voice_id': voice_id, 'model': self.model, 'ready': False, 'status': 'UNKNOWN'}
        for attempt in range(3):
            try:
                status = self.query_voice(voice_id)
            except APIError:
                break
            if status['status'] != 'DEPLOYING':
                break
            if attempt < 2:
                time.sleep(1)
        status['reference_text_used'] = False
        status['message'] = '复刻音色已就绪，可用它生成新讲解。' if status['ready'] else '音色已创建，尚未确认就绪。请保留音色 ID，稍后查询；不要重复创建。'
        return status


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    server_version = 'DUCKO/1.0'
    protocol_version = 'HTTP/1.0'

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, fmt, *args):
        # Do not log input text, audio, credentials, or query parameters.
        pass

    def send(self, status, data, content_type='application/json; charset=utf-8', extra_headers=None):
        if isinstance(data, dict):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        extra_headers = dict(extra_headers or {})
        self.send_header('Cache-Control', extra_headers.pop('Cache-Control', 'no-store' if content_type.startswith('application/json') else 'no-cache'))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Permissions-Policy', 'microphone=(self), camera=()')
        self.send_header('X-Frame-Options', 'DENY')
        for name, value in extra_headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def fail(self, error):
        self.send(error.status, {'error': error.message, 'code': error.code})

    def local_request(self):
        host = self.headers.get('Host', '')
        valid_hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if host not in valid_hosts:
            raise APIError(403, '仅允许本机访问。', 'invalid_host')
        # A user may open the local page from a link in another application.
        # Permit only top-level static document navigation in that case. API
        # reads, writes and embedded documents keep the same-origin checks.
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        static_navigation = (self.command in ('GET', 'HEAD')
                             and not path.startswith('/api')
                             and self.headers.get('Sec-Fetch-Mode') == 'navigate'
                             and self.headers.get('Sec-Fetch-Dest') == 'document')
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + host and not static_navigation:
            raise APIError(403, '不允许跨站请求。请在本机页面操作。', 'invalid_origin')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site' and not static_navigation:
            raise APIError(403, '不允许跨站请求。', 'invalid_origin')

    def do_HEAD(self):
        self.do_GET()

    def send_audio(self, raw):
        headers = {'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store'}
        byte_range = self.headers.get('Range')
        if not byte_range:
            return self.send(200, raw, 'audio/wav', headers)
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', byte_range)
        try:
            if not match or not any(match.groups()):
                raise ValueError('invalid range')
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), len(raw) - 1) if last else len(raw) - 1
            else:
                start, end = max(0, len(raw) - int(last)), len(raw) - 1
            if start > end or start >= len(raw):
                raise ValueError('outside file')
        except ValueError:
            headers['Content-Range'] = 'bytes */' + str(len(raw))
            return self.send(416, b'', 'audio/wav', headers)
        headers['Content-Range'] = f'bytes {start}-{end}/{len(raw)}'
        return self.send(206, raw[start:end + 1], 'audio/wav', headers)

    def do_GET(self):
        try:
            self.local_request()
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == '/api/status':
                return self.send(200, self.server.app.status())
            if parsed.path.startswith('/api/audio/'):
                return self.send_audio(self.server.app.get_audio(parsed.path.removeprefix('/api/audio/')))
            if parsed.path == '/api/voice':
                voice = urllib.parse.parse_qs(parsed.query).get('voice_id', [''])[0]
                return self.send(200, self.server.app.query_voice(voice))
            if parsed.path.startswith('/api/'):
                raise APIError(404, '接口不存在。', 'not_found')
            path = urllib.parse.unquote(parsed.path)
            if '\\' in path or '\0' in path:
                raise APIError(403, '路径不可访问。', 'forbidden_path')
            parts = path.lstrip('/').split('/')
            if any(p.startswith('.') for p in parts if p):
                raise APIError(403, '路径不可访问。', 'forbidden_path')
            target = (self.server.root / ('index.html' if path == '/' else path.lstrip('/'))).resolve()
            try:
                target.relative_to(self.server.root)
            except ValueError:
                raise APIError(403, '路径不可访问。', 'forbidden_path') from None
            allowed = {'.html', '.css', '.js', '.json', '.png', '.jpg', '.jpeg', '.svg', '.webp', '.ico', '.wav', '.mp3', '.m4a', '.ogg', '.webm', '.woff', '.woff2', '.ttf', '.gz'}
            rel = target.relative_to(self.server.root)
            if len(rel.parts) > 1 and rel.parts[0] not in ('assets', 'audio', 'vendor', 'models-browser'):
                raise APIError(404, '文件不存在。', 'not_found')
            model_shard = (len(rel.parts) == 2 and rel.parts[0] == 'models-browser'
                           and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz\.part(?:0[1-9]|[1-9][0-9])\.bin', rel.name) is not None)
            if not target.is_file() or (target.suffix.lower() not in allowed and not model_shard):
                raise APIError(404, '文件不存在。', 'not_found')
            mime = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
            if target.suffix.lower() == '.js':
                mime = 'text/javascript'
            elif target.suffix.lower() == '.gz':
                mime = 'application/gzip'
            elif model_shard:
                mime = 'application/octet-stream'
            self.send(200, target.read_bytes(), mime)
        except APIError as e:
            self.fail(e)
        except (OSError, ValueError):
            self.fail(APIError(400, '请求无效或文件不可读。', 'invalid_request'))

    def do_POST(self):
        acquired = False
        try:
            self.local_request()
            if self.path not in ('/api/tts', '/api/clone', '/api/asr'):
                raise APIError(404, '接口不存在。', 'not_found')
            if self.headers.get('Content-Type', '').split(';')[0].lower() != 'application/json':
                raise APIError(415, '接口只接受 JSON。', 'invalid_content_type')
            if self.headers.get('Transfer-Encoding'):
                raise APIError(400, '不支持此传输方式。', 'invalid_request')
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise APIError(400, '请求长度无效。', 'invalid_length') from None
            if length < 1 or length > MAX_BODY:
                raise APIError(413, '请求为空或过大。', 'request_too_large')
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise APIError(400, '请求不完整。', 'incomplete_body')
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeError):
                raise APIError(400, 'JSON 格式错误。', 'invalid_json') from None
            if not isinstance(body, dict):
                raise APIError(400, 'JSON 需为对象。', 'invalid_json')
            acquired = self.server.app.slots.acquire(blocking=False)
            if not acquired:
                raise APIError(429, '已有请求正在处理，请稍后再试。', 'busy')
            if self.path == '/api/tts':
                self.send(200, self.server.app.tts(body))
            elif self.path == '/api/asr':
                self.send(200, self.server.app.asr.transcribe(body))
            else:
                result = self.server.app.clone(body)
                self.send(200 if result['ready'] else 202, result)
        except APIError as e:
            self.fail(e)
        except (socket.timeout, TimeoutError):
            self.fail(APIError(408, '读取请求超时。', 'request_timeout'))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.fail(APIError(500, '本地服务处理失败。', 'internal_error'))
        finally:
            if acquired:
                self.server.app.slots.release()


def make_server(host, port, root=None, app=None):
    if host not in ('127.0.0.1', 'localhost'):
        raise ValueError('This demo deliberately binds to localhost only.')
    httpd = LocalServer((host, port), Handler)
    httpd.root = Path(root or Path(__file__).parent).resolve()
    httpd.app = app or App()
    return httpd


def main():
    parser = argparse.ArgumentParser(description='DUCKO local voice demo server')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('--port must be between 1024 and 65535')
    server = make_server('127.0.0.1', args.port)
    print(f'DUCKO: http://127.0.0.1:{args.port}')
    print('Cloud configured (not yet verified).' if server.app.configured else 'Offline sample mode. No API credentials configured.')
    print('Local ASR languages:', ', '.join(server.app.asr.status()['asr_languages']) or 'not installed; see README_ASR.md')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
