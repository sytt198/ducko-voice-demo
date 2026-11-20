#!/usr/bin/env python3
"""从语料 JSON 生成 DUCKO 演示音频（中英 × 三音色），并更新 manifest.json。

用法：
  python regenerate_audio.py --corpus <corpus.json> [--ids id1,id2] [--force]

- 不传 --ids：处理全部条目；传 --ids：只处理指定条目（用于增量更新）。
- 默认跳过已存在且 >1KB 的音频；--force 强制重生成（改了答案文本时必须用）。
- 保留 manifest 里未涉及条目的记录，只替换本次生成的条目。
"""

import argparse
import asyncio
import json
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VOICES = {
    "zh": {
        "warm": ("zh-CN-XiaoxiaoNeural", "-5%", "+0Hz"),
        "happy": ("zh-CN-XiaoyiNeural", "+8%", "+6Hz"),
        "calm": ("zh-CN-YunxiNeural", "-8%", "-3Hz"),
    },
    "en": {
        "warm": ("en-GB-SoniaNeural", "-3%", "+0Hz"),
        "happy": ("en-GB-LibbyNeural", "+8%", "+4Hz"),
        "calm": ("en-GB-RyanNeural", "-7%", "-3Hz"),
    },
}
MANIFEST = ROOT / "audio" / "dialogue" / "manifest.json"
TODAY = date.today().isoformat()


def load_manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return []


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--ids", default="", help="逗号分隔的条目ID，留空表示全部")
    ap.add_argument("--force", action="store_true", help="强制重生成（答案文本变更时用）")
    args = ap.parse_args()

    import edge_tts

    data = json.loads(args.corpus.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    wanted = {x.strip() for x in args.ids.split(",") if x.strip()}
    targets = [e for e in entries if not wanted or e["id"] in wanted]
    print(f"目标条目：{[e['id'] for e in targets]}")

    manifest = load_manifest()
    keep = [m for m in manifest if m.get("id") not in {e["id"] for e in targets}]
    new_records = []

    async def generate(entry, lang, mood):
        voice, rate, pitch = VOICES[lang][mood]
        text = entry["answer"][lang]
        rel = f"audio/dialogue/{entry['id']}-{lang}-{mood}.mp3"
        output = ROOT / rel
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and output.stat().st_size > 1024 and not args.force:
            print(f"  [跳过已存在] {rel}")
        else:
            for attempt in range(3):
                try:
                    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(output))
                    break
                except Exception as exc:
                    if attempt == 2:
                        raise
                    print(f"    重试 {attempt + 1}: {exc}")
                    await asyncio.sleep(1 + attempt)
        dur = json.loads(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(output)], text=True))["format"]["duration"]
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"],
                       check=True, capture_output=True)
        rec = {
            "id": entry["id"], "language": lang, "mood": mood, "file": rel,
            "text": text, "provider": "Microsoft Edge Read Aloud",
            "client": "edge-tts 7.3.1", "voice": voice, "rate": rate, "pitch": pitch,
            "duration": float(dur), "bytes": output.stat().st_size,
            "kind": "preset neural voice with prosody adjustment; not instruction-controlled emotion and not a clone",
            "generated_at": TODAY,
        }
        new_records.append(rec)
        print(f"  [生成] {rel} ({rec['bytes']} bytes)")

    async def run():
        sem = asyncio.Semaphore(3)
        async def guarded(e, l, m):
            async with sem:
                await generate(e, l, m)
        await asyncio.gather(*(guarded(e, l, m) for e in targets for l in VOICES for m in VOICES[l]))

    asyncio.run(run())
    manifest = keep + new_records
    manifest.sort(key=lambda m: (m["id"], m["language"], m["mood"]))
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：本次生成 {len(new_records)} 条音频，manifest 共 {len(manifest)} 条。")


if __name__ == "__main__":
    main()
