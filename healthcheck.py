#!/usr/bin/env python3
"""Read-only local checks; optional silence recognition does not use the mic."""
import argparse
import base64
import io
import json
import urllib.error
import urllib.request
import wave


def local_client():
    # Loopback traffic must remain on this computer, not use a system proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check_server(port=8770, timeout=2):
    url = f'http://127.0.0.1:{port}'
    try:
        with local_client().open(url + '/api/status', timeout=timeout) as response:
            if not response.headers.get('Server', '').startswith('DUCKO/'):
                return {'ok': False, 'url': url, 'reason': 'This port is serving another application.'}
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError('unexpected response size')
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get('asr_engine') != 'vosk':
                return {'ok': False, 'url': url, 'reason': 'This is not the current DUCKO recognition service.'}
            return {'ok': True, 'url': url, 'asr_available': bool(data.get('asr_available')),
                    'asr_languages': data.get('asr_languages', []),
                    'asr_model_loaded': data.get('asr_model_loaded', []),
                    'asr_message': data.get('asr_message', '')}
    except (OSError, ValueError, urllib.error.URLError):
        return {'ok': False, 'url': url, 'reason': 'The local service did not respond.'}


def recognition_check(port, language):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\0\0' * 16000)
    body = {'audio_base64': base64.b64encode(output.getvalue()).decode('ascii'),
            'mime_type': 'audio/wav', 'language': language}
    request = urllib.request.Request(f'http://127.0.0.1:{port}/api/asr',
        data=json.dumps(body).encode('utf-8'), headers={'Content-Type': 'application/json'})
    try:
        with local_client().open(request, timeout=60) as response:
            data = json.load(response)
        return {'ok': data.get('engine') == 'vosk' and data.get('offline') is True and data.get('text') == '',
                'language': language, 'test': 'one second of generated silence',
                'microphone_tested': False}
    except (OSError, ValueError, urllib.error.URLError):
        return {'ok': False, 'language': language, 'microphone_tested': False,
                'reason': 'Recognition failed. Check the model and Python environment.'}


def main():
    parser = argparse.ArgumentParser(description='Check the local DUCKO service')
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--recognition-test', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Port must be between 1024 and 65535')
    result = check_server(args.port)
    if args.recognition_test and result.get('ok') and result.get('asr_languages'):
        result['recognition_test'] = recognition_check(args.port, result['asr_languages'][0])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get('ok') and (not args.recognition_test or result.get('recognition_test', {}).get('ok')) else 1)


if __name__ == '__main__':
    main()
