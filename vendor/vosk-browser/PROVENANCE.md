# Vosk Browser

Bundled unmodified `vosk-browser` 0.0.8 from the official npm package.

- Package: https://www.npmjs.com/package/vosk-browser
- Source: https://github.com/ccoreilly/vosk-browser
- Tarball: https://registry.npmjs.org/vosk-browser/-/vosk-browser-0.0.8.tgz
- npm license declaration: Apache-2.0
- Retrieval date: 2026-11-02
- Verified npm SHA-512 integrity: `df9MuChirUGKxP/+4k8tBV6hJOic8IRdJXv64+ET0Ue5CddOzLZINiHOWCka765gBzHJWNtQKgaYakS0FXZIJA==`

The distributed JavaScript contains the Vosk WebAssembly engine and a Blob-based Web Worker. Its dependency notices remain embedded in the original file. `LICENSE-2.0.txt` is the standard Apache 2.0 license downloaded from https://www.apache.org/licenses/LICENSE-2.0.txt.

DUCKO uses the pinned runtime's worker handle only to forcibly stop CPU work on cancellation. Normal recognition calls use `Model`, `KaldiRecognizer(16000)`, `acceptWaveformFloat`, `retrieveFinalResult`, and `remove`.

For split-file delivery, the application adapter wraps the Worker constructor only during the synchronous Vosk Model construction, then restores it immediately. The wrapper imports the original unmodified worker and routes only the selected model fetch to a SHA-256-verified Blob. Vosk still receives a stable model URL for its IndexedDB key. No vendor source files are patched.
