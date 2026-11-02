# Browser Vosk models

These are tar.gz repacks of the official models already downloaded for this demo.
The archive root is `model/`; all model file contents are unchanged.

- Chinese: vosk-model-small-cn-0.22, https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip
- English: vosk-model-small-en-us-0.15, https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
- Model listing and licenses: https://alphacephei.com/vosk/models
- License for both models: Apache 2.0
- Retrieval/repack date: 2026-11-02

See `manifest.json` for archive and part sizes and SHA-256 checksums. Each archive is also split into seven parts, at most 6 MiB each, named `*.tar.gz.part01.bin` through `*.tar.gz.part07.bin`. The website uses all listed parts; the original large archives may remain only in the development directory.

The adapter verifies every part and the assembled archive before passing it to Vosk. A scoped Worker fetch wrapper maps a stable model URL to the verified Blob, so Vosk's IndexedDB cache key does not change with temporary Blob UUIDs. Verified archives may also be cached in the site's Cache API. The runtime downloads only the selected language. User recordings are not stored in these model caches.
