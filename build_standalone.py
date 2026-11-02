#!/usr/bin/env python3
"""Embed the demo's actual image and audio; standard library only."""
import base64
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parent
html = (root / 'index.html').read_text(encoding='utf-8')
for name in ['samples.js', 'dialogue-data.js', 'dialogue-engine.js', 'browser-asr.js', 'interaction.js']:
    content = (root / name).read_text(encoding='utf-8')
    if name in ['samples.js', 'dialogue-data.js']:
        for path in (root / 'audio').rglob('*.mp3'):
            relative = path.relative_to(root).as_posix()
            if relative not in content:
                continue
            audio = base64.b64encode(path.read_bytes()).decode('ascii')
            content = content.replace(json.dumps(relative), json.dumps('data:audio/mpeg;base64,' + audio))
    pattern = r'<script src="' + re.escape(name) + r'(?:\?[^"<>]*)?"></script>'
    html, count = re.subn(pattern, lambda _: '<script>\n' + content + '\n</script>', html)
    if count != 1:
        raise ValueError('Expected exactly one script reference: ' + name)
image = base64.b64encode((root / 'assets/concept.png').read_bytes()).decode('ascii')
html = html.replace('src="assets/concept.png"', 'src="data:image/png;base64,' + image + '"')
html = html.replace('<link rel="stylesheet" href="interaction.css">', '<style>\n' + (root / 'interaction.css').read_text(encoding='utf-8') + '\n</style>')
target = root / 'DUCKO语音交互.html'
target.write_text(html, encoding='utf-8')
# Update the previously delivered link as well.
(root / 'DUCKO声音体验_双击打开.html').write_text(html, encoding='utf-8')
print('Standalone HTML ready:', target.name, target.stat().st_size, 'bytes')
