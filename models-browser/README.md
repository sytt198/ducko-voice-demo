# Browser Vosk models

These are tar.gz repacks of the official models already downloaded for this demo.
The archive root is `model/`; all model file contents are unchanged. Current delivery filenames end in `-browser-v2.tar.gz`.

- Chinese: vosk-model-small-cn-0.22, https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip
- English: vosk-model-small-en-us-0.15, https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
- Model listing and licenses: https://alphacephei.com/vosk/models
- License for both models: Apache 2.0
- Retrieval/repack date: 2026-11-02

See `manifest.json` for archive and part sizes and SHA-256 checksums. Each archive is also split into seven parts, at most 6 MiB each, named `*.tar.gz.part01.bin` through `*.tar.gz.part07.bin`. The website uses all listed parts; the original large archives may remain only in the development directory.

The adapter verifies every part and the assembled archive before passing it to Vosk. A scoped Worker fetch wrapper maps a stable model URL to the verified Blob, so Vosk's IndexedDB cache key does not change with temporary Blob UUIDs. Verified archives may also be cached in the site's Cache API. The runtime downloads only the selected language. User recordings are not stored in these model caches.

The v2 package contains explicit entries for every directory, with mode 0755; regular files have mode 0644. The earlier file-only archive caused the bundled libarchive to leave implicit parent directories at mode 000. Extraction then appeared to succeed, but Vosk's subsequent filesystem sync failed with EACCES (`FS error`). The new filenames isolate the corrected archive and model cache paths. Old archives and parts may remain in the development directory as diagnostic evidence; publish only the parts referenced by the current manifest.

Regression check: from the demo directory run `python -m unittest test_model_archives -v`. Required checks reconstruct the archive in memory from the published manifest and parts, validate directory traversal and file permissions, and verify every part and complete-archive hash. Neither an original tar.gz nor native models are required. A separate optional test compares every packed file with the original native models; if `models/` is absent, only that test is skipped with an explicit message.
