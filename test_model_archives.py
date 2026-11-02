"""Model package checks. Run: python -m unittest test_model_archives -v.

All required checks use published deployment shards, not an unpublished tar.gz.
Original native-model byte comparison is an optional local-only check.
It does not claim to test a browser, IndexedDB, or microphone permissions.
"""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import tarfile
import unittest

ROOT = Path(__file__).resolve().parent


def validate_structure(members):
    by_name = {member.name.rstrip('/'): member for member in members}
    if len(by_name) != len(members):
        raise AssertionError('Duplicate archive path')
    root = by_name.get('model')
    if root is None or not root.isdir():
        raise AssertionError('Missing explicit model directory')
    for name, member in by_name.items():
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or path.parts[0] != 'model':
            raise AssertionError(f'Invalid archive path: {name}')
        if not (member.isdir() or member.isfile()):
            raise AssertionError(f'Unsupported archive entry: {name}')
        expected = 0o755 if member.isdir() else 0o644
        if member.mode != expected:
            raise AssertionError(f'Wrong permissions on {name}: {member.mode:o}')
        for parent in path.parents:
            if str(parent) == '.':
                continue
            entry = by_name.get(str(parent))
            if entry is None or not entry.isdir() or entry.mode & 0o111 != 0o111:
                raise AssertionError(f'Missing or non-traversable ancestor: {parent}')
    return by_name


def digest(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        result.update(chunk)
    return result.hexdigest()


class BrowserModelArchives(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = json.loads((ROOT / 'models-browser/manifest.json').read_text('utf-8'))

    def assembled_archive(self, record):
        return io.BytesIO(b''.join((ROOT / 'models-browser' / part['file']).read_bytes()
                                  for part in record['parts']))

    def test_archive_structure_and_permissions(self):
        self.assertEqual({r['language'] for r in self.records}, {'zh', 'en'})
        for record in self.records:
            with self.subTest(language=record['language']):
                self.assertTrue(record['file'].endswith('-browser-v2.tar.gz'))
                with self.assembled_archive(record) as stream, tarfile.open(fileobj=stream, mode='r:gz') as archive:
                    entries = validate_structure(archive.getmembers())
                    for required in ('model/am/final.mdl', 'model/conf/mfcc.conf', 'model/conf/model.conf'):
                        self.assertIn(required, entries)
                        self.assertTrue(entries[required].isfile())
                        self.assertGreater(entries[required].size, 0)
                    for name, entry in entries.items():
                        if entry.isfile():
                            with archive.extractfile(name) as payload:
                                self.assertEqual(len(payload.read()), entry.size, name)

    def test_original_native_payloads_when_available(self):
        missing = [record['model'] for record in self.records
                   if not (ROOT / 'models' / record['model']).is_dir()]
        if missing:
            self.skipTest('Optional native-model byte comparison: native models are not published; missing ' + ', '.join(missing))
        for record in self.records:
            with self.subTest(language=record['language']):
                source = ROOT / 'models' / record['model']
                expected = {'model/' + p.relative_to(source).as_posix(): p
                            for p in source.rglob('*') if p.is_file()}
                with self.assembled_archive(record) as stream, tarfile.open(fileobj=stream, mode='r:gz') as archive:
                    entries = validate_structure(archive.getmembers())
                    self.assertEqual({name for name, entry in entries.items() if entry.isfile()}, set(expected))
                    for name, original in expected.items():
                        with archive.extractfile(name) as packed, original.open('rb') as native:
                            self.assertEqual(digest(packed), digest(native), name)

    def test_shards_and_manifest_reconstruct_archive(self):
        for record in self.records:
            with self.subTest(language=record['language']):
                joined = hashlib.sha256()
                total = 0
                for number, part in enumerate(record['parts'], 1):
                    self.assertEqual(part['file'], record['file'] + f'.part{number:02d}.bin')
                    data = (ROOT / 'models-browser' / part['file']).read_bytes()
                    self.assertEqual(len(data), part['bytes'])
                    self.assertLessEqual(len(data), 6 * 1024 * 1024)
                    self.assertEqual(hashlib.sha256(data).hexdigest(), part['sha256'])
                    total += len(data)
                    joined.update(data)
                self.assertEqual(total, record['bytes'])
                self.assertEqual(joined.hexdigest(), record['sha256'])

    def test_missing_or_inaccessible_directories_are_rejected(self):
        root = tarfile.TarInfo('model')
        root.type, root.mode = tarfile.DIRTYPE, 0o755
        file = tarfile.TarInfo('model/am/final.mdl')
        file.mode = 0o644
        with self.assertRaisesRegex(AssertionError, 'ancestor'):
            validate_structure([root, file])
        directory = tarfile.TarInfo('model/am')
        directory.type, directory.mode = tarfile.DIRTYPE, 0
        with self.assertRaisesRegex(AssertionError, 'permissions|ancestor'):
            validate_structure([root, directory, file])


if __name__ == '__main__':
    unittest.main()
