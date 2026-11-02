"""Offline tests; never contact or bill a model service."""
import base64
import io
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import wave
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import server


def wav_sample(rate=24000, duration=6, channels=1):
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b'\0\0' * int(rate * duration) * channels)
    return base64.b64encode(out.getvalue()).decode()


class PayloadTests(unittest.TestCase):
    def test_unconfigured_does_not_call_cloud(self):
        app = server.App({})
        with patch.object(app, 'cloud') as call:
            with self.assertRaises(server.APIError) as error:
                app.tts({'text': '你好', 'emotion': 'warm'})
            self.assertEqual(error.exception.status, 503)
            call.assert_not_called()

    def test_emotion_and_clone_voice_share_model(self):
        app = server.App({'DASHSCOPE_API_KEY': 'test-secret', 'DASHSCOPE_WORKSPACE_ID': 'ws123'})
        with patch.object(app, 'cloud', return_value={'output': {'audio': {'url': 'https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/test.wav'}}}) as call, patch.object(app, 'cache_audio', return_value='/api/audio/' + 'a' * 32 + '.wav'):
            result = app.tts({'text': '你好', 'language': 'zh', 'emotion': 'happy', 'voice_id': 'qwen-audio-3.1-tts-flash-ducko-123'})
            request = call.call_args.args[1]
            self.assertIn('活泼', request['input']['instruction'])
            self.assertEqual(request['input']['voice'], 'qwen-audio-3.1-tts-flash-ducko-123')
            self.assertEqual(result['audio_url'], '/api/audio/' + 'a' * 32 + '.wav')
            self.assertTrue(result['cached'])

    def test_webm_is_rejected_before_cloud_call(self):
        app = server.App({'DASHSCOPE_API_KEY': 'test-secret', 'DASHSCOPE_WORKSPACE_ID': 'ws123'})
        with patch.object(app, 'cloud') as call:
            with self.assertRaises(server.APIError) as error:
                app.clone({'audio_base64': 'ZmFrZQ==', 'mime_type': 'audio/webm'})
            self.assertEqual(error.exception.status, 400)
            call.assert_not_called()

    def test_clone_queries_readiness_and_does_not_send_transcript(self):
        app = server.App({'DASHSCOPE_API_KEY': 'test-secret', 'DASHSCOPE_WORKSPACE_ID': 'ws123'})
        responses = [{'output': {'voice_id': 'qwen-audio-3.1-tts-flash-ducko-abc'}}, {'output': {'status': 'OK'}}]
        with patch.object(app, 'cloud', side_effect=responses) as call:
            result = app.clone({'audio_base64': wav_sample(), 'mime_type': 'audio/wav', 'reference_text': 'hello'})
            self.assertTrue(result['ready'])
            self.assertFalse(result['reference_text_used'])
            request = call.call_args_list[0].args[1]
            self.assertEqual(request['model'], 'voice-enrollment')
            self.assertEqual(request['input']['target_model'], 'qwen-audio-3.1-tts-flash')
            self.assertNotIn('reference_text', request['input'])

    def test_reject_mismatched_voice_model(self):
        app = server.App({'DASHSCOPE_API_KEY': 'test-secret', 'DASHSCOPE_WORKSPACE_ID': 'ws123'})
        with self.assertRaises(server.APIError):
            app.tts({'text': '你好', 'voice_id': 'qwen-audio-3.0-tts-flash-abc'})

    def test_malformed_emotion_is_a_client_error(self):
        app = server.App({'DASHSCOPE_API_KEY': 'test-secret', 'DASHSCOPE_WORKSPACE_ID': 'ws123'})
        with self.assertRaises(server.APIError) as error:
            app.tts({'text': '你好', 'emotion': []})
        self.assertEqual(error.exception.status, 400)


class AudioCacheTests(unittest.TestCase):
    def test_audio_is_downloaded_over_https_without_api_key(self):
        app = server.App({'DASHSCOPE_API_KEY': 'never-send-to-audio-host', 'DASHSCOPE_WORKSPACE_ID': 'ws123'})
        wav = base64.b64decode(wav_sample())
        with patch.object(app.audio_opener, 'open', return_value=io.BytesIO(wav)) as download:
            url = app.cache_audio('http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/test.wav?signature=abc')
            request = download.call_args.args[0]
            self.assertTrue(request.full_url.startswith('https://'))
            self.assertNotIn('Authorization', request.headers)
            self.assertNotIn('never-send-to-audio-host', str(request.headers))
            self.assertEqual(app.get_audio(url.removeprefix('/api/audio/')), wav)

    def test_non_aliyun_audio_hosts_are_never_requested(self):
        app = server.App({})
        urls = ('https://127.0.0.1/audio.wav', 'https://example.org/audio.wav',
                'https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com.evil.example/a.wav',
                'https://user@dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.wav',
                'https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com:8443/a.wav')
        with patch.object(app.audio_opener, 'open') as download:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(server.APIError):
                    app.cache_audio(url)
            download.assert_not_called()

    def test_non_audio_response_is_rejected(self):
        app = server.App({})
        with patch.object(app.audio_opener, 'open', return_value=io.BytesIO(b'<html>not audio</html>')):
            with self.assertRaises(server.APIError):
                app.cache_audio('https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.wav')

    def test_cache_expiry_is_reported_as_gone(self):
        app = server.App({})
        with patch.object(app.audio_opener, 'open', return_value=io.BytesIO(base64.b64decode(wav_sample()))):
            url = app.cache_audio('https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.wav')
        with patch.object(server.time, 'monotonic', return_value=10**20):
            with self.assertRaises(server.APIError) as error:
                app.get_audio(url.removeprefix('/api/audio/'))
            self.assertEqual(error.exception.status, 410)


class LocalASRTests(unittest.TestCase):
    def test_rejects_wrong_format_and_duration_before_loading(self):
        asr = server.LocalASR({})
        invalid = [dict(audio_base64='not-base64'),
                   dict(audio_base64=wav_sample(), mime_type='audio/webm'),
                   dict(audio_base64=wav_sample(rate=24000)),
                   dict(audio_base64=wav_sample(rate=16000, duration=21)),
                   dict(audio_base64=wav_sample(rate=16000, duration=.1)),
                   dict(audio_base64=wav_sample(rate=16000, channels=2))]
        with patch.object(asr, 'load_model') as load:
            for body in invalid:
                with self.subTest(body=list(body)), self.assertRaises(server.APIError) as e:
                    asr.transcribe(body)
                self.assertEqual(e.exception.status, 400)
            load.assert_not_called()

    def test_missing_package_disables_asr_and_does_not_request_cloud(self):
        asr = server.LocalASR({})
        with patch.object(server.importlib.util, 'find_spec', return_value=None):
            self.assertFalse(asr.status()['asr_available'])
            with self.assertRaises(server.APIError) as e:
                asr.transcribe({'audio_base64': wav_sample(rate=16000)})
            self.assertEqual(e.exception.code, 'asr_not_ready')

    def test_combines_segments_and_final_result(self):
        class Recognizer:
            def __init__(self, model, rate):
                assert rate == 16000
                self.count = 0
            def AcceptWaveform(self, data):
                self.count += 1
                return self.count == 1
            def Result(self):
                return json.dumps({'text': '宁波 诺丁汉 大学'})
            def FinalResult(self):
                return json.dumps({'text': '在 哪里'})
        asr = server.LocalASR({})
        with patch.object(asr, 'load_model', return_value=object()), patch.dict('sys.modules', {'vosk': SimpleNamespace(KaldiRecognizer=Recognizer)}):
            result = asr.transcribe({'audio_base64': wav_sample(rate=16000), 'language': 'zh'})
        self.assertEqual(result['text'], '宁波诺丁汉大学在哪里')
        self.assertTrue(result['offline'])
        self.assertEqual(result['duration_seconds'], 6)

    def test_silence_returns_empty_text_without_a_fabricated_question(self):
        class Recognizer:
            def __init__(self, *args): pass
            def AcceptWaveform(self, data): return False
            def FinalResult(self): return '{"text":""}'
        asr = server.LocalASR({})
        with patch.object(asr, 'load_model', return_value=object()), patch.dict('sys.modules', {'vosk': SimpleNamespace(KaldiRecognizer=Recognizer)}):
            result = asr.transcribe({'audio_base64': wav_sample(rate=16000)})
        self.assertEqual(result['text'], '')

    def test_one_recognition_request_at_a_time(self):
        asr = server.LocalASR({})
        asr.recognition_slot.acquire()
        try:
            with self.assertRaises(server.APIError) as e:
                asr.transcribe({'audio_base64': wav_sample(rate=16000)})
            self.assertEqual(e.exception.status, 429)
        finally:
            asr.recognition_slot.release()


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workspace = Path(__file__).resolve().parent
        cls.folder = tempfile.TemporaryDirectory(prefix='backend-test-', dir=workspace)
        cls.root = Path(cls.folder.name).resolve()
        if not cls.root.is_relative_to(workspace):
            raise RuntimeError('Test directory must remain inside this demo folder.')
        (cls.root / 'index.html').write_text('DUCKO')
        (cls.root / '.env').write_text('secret')
        (cls.root / 'server.py').write_text('secret')
        (cls.root / 'models-browser').mkdir()
        (cls.root / 'models-browser' / 'zh.tar.gz').write_bytes(b'browser-model-test')
        (cls.root / 'models-browser' / 'vosk-model-small-cn-0.22.tar.gz.part01.bin').write_bytes(b'model-shard')
        (cls.root / 'models-browser' / 'unknown.bin').write_bytes(b'not-public')
        (cls.root / 'models-browser' / 'zh.tar.gz.part00.bin').write_bytes(b'not-public')
        (cls.root / 'models-browser' / 'zh.tar.gz.part1.bin').write_bytes(b'not-public')
        (cls.root / 'zh.tar.gz.part01.bin').write_bytes(b'not-public')
        (cls.root / 'vendor').mkdir()
        (cls.root / 'vendor' / 'test.js').write_text('/* test */')
        (cls.root / 'vendor' / 'zh.tar.gz.part01.bin').write_bytes(b'not-public')
        (cls.root / 'models').mkdir()
        (cls.root / 'models' / 'private.json').write_text('{}')
        cls.httpd = server.make_server('127.0.0.1', 0, cls.root, server.App({}))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.httpd.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close(); cls.folder.cleanup()

    def test_status_is_honest_and_has_no_secrets(self):
        data = json.load(urllib.request.urlopen(self.url + '/api/status'))
        self.assertFalse(data['configured'])
        self.assertFalse(data['clone_available'])
        self.assertNotIn('api_key', data)
        self.assertEqual(data['asr_engine'], 'vosk')
        self.assertIn('asr_languages', data)

    def test_asr_endpoint_returns_recognized_text(self):
        result = {'text': '你好', 'language': 'zh', 'engine': 'vosk', 'offline': True}
        with patch.object(self.httpd.app.asr, 'transcribe', return_value=result) as recognize:
            request = urllib.request.Request(self.url + '/api/asr', data=b'{"audio_base64":"test","language":"zh"}', headers={'Content-Type': 'application/json'})
            self.assertEqual(json.load(urllib.request.urlopen(request)), result)
            recognize.assert_called_once()

    def test_cross_site_cannot_activate_local_recognizer(self):
        with patch.object(self.httpd.app.asr, 'transcribe') as recognize:
            request = urllib.request.Request(self.url + '/api/asr', data=b'{}', headers={'Content-Type': 'application/json', 'Origin': 'https://example.org'})
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(request)
            self.assertEqual(e.exception.code, 403)
            recognize.assert_not_called()

    def test_external_link_can_open_static_page_as_top_level_navigation(self):
        headers = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate',
                   'Sec-Fetch-Dest': 'document', 'Origin': 'https://example.org'}
        for method in ('GET', 'HEAD'):
            request = urllib.request.Request(self.url + '/', headers=headers, method=method)
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b'DUCKO' if method == 'GET' else b'')

    def test_external_navigation_does_not_allow_api_or_iframe_requests(self):
        navigation = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate',
                      'Sec-Fetch-Dest': 'document', 'Origin': 'https://example.org'}
        requests = [urllib.request.Request(self.url + '/api/status', headers=navigation),
                    urllib.request.Request(self.url + '/%61pi/status', headers=navigation),
                    urllib.request.Request(self.url + '/', headers={**navigation, 'Sec-Fetch-Dest': 'iframe'}),
                    urllib.request.Request(self.url + '/api/asr', data=b'{}', headers={**navigation, 'Content-Type': 'application/json'})]
        for request in requests:
            with self.subTest(path=request.full_url), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, '403' if isinstance(error.exception.code, str) else 403)

    def test_static_and_secret_denial(self):
        self.assertEqual(urllib.request.urlopen(self.url + '/').read(), b'DUCKO')
        for path in ('/.env', '/server.py', '/%2e%2e/test.txt', '/audio/../../server.py', '/models/private.json'):
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(self.url + path)
            self.assertIn(e.exception.code, (400, 403, 404))

    def test_browser_asr_assets_are_served_without_exposing_native_models(self):
        with urllib.request.urlopen(self.url + '/models-browser/zh.tar.gz') as response:
            self.assertEqual(response.headers['Content-Type'], 'application/gzip')
            self.assertEqual(response.read(), b'browser-model-test')
        with urllib.request.urlopen(self.url + '/vendor/test.js') as response:
            self.assertEqual(response.headers['Content-Type'], 'text/javascript')

    def test_only_named_browser_model_shards_are_public_binary_files(self):
        path = '/models-browser/vosk-model-small-cn-0.22.tar.gz.part01.bin'
        with urllib.request.urlopen(self.url + path) as response:
            self.assertEqual(response.headers['Content-Type'], 'application/octet-stream')
            self.assertEqual(response.read(), b'model-shard')
        for path in ('/models-browser/unknown.bin', '/models-browser/zh.tar.gz.part00.bin',
                     '/models-browser/zh.tar.gz.part1.bin', '/zh.tar.gz.part01.bin',
                     '/vendor/zh.tar.gz.part01.bin'):
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)

    def test_foreign_origin_cannot_spend_credentials(self):
        request = urllib.request.Request(self.url + '/api/tts', data=b'{"text":"hello"}', headers={'Content-Type': 'application/json', 'Origin': 'https://example.org'})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(request)
        self.assertEqual(e.exception.code, 403)

    def test_unknown_routes_are_json_errors(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(self.url + '/api/unknown')
        self.assertEqual(e.exception.code, 404)
        self.assertIn('error', json.load(e.exception))

    def test_generated_audio_has_same_origin_and_supports_seeking(self):
        wav = base64.b64decode(wav_sample())
        with patch.object(self.httpd.app.audio_opener, 'open', return_value=io.BytesIO(wav)):
            path = self.httpd.app.cache_audio('https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/test.wav')
        response = urllib.request.urlopen(self.url + path)
        self.assertEqual(response.headers['Content-Type'], 'audio/wav')
        self.assertEqual(response.read(), wav)
        request = urllib.request.Request(self.url + path, headers={'Range': 'bytes=0-43'})
        response = urllib.request.urlopen(request)
        self.assertEqual(response.status, 206)
        self.assertEqual(response.read(), wav[:44])
        self.assertEqual(response.headers['Content-Range'], 'bytes 0-43/' + str(len(wav)))


if __name__ == '__main__':
    unittest.main()
