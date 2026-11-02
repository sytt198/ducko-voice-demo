#!/usr/bin/env python3
"""Download an official small Vosk model to this demo, using HTTPS only."""
import argparse
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.request
import zipfile

MODELS = {'zh': 'vosk-model-small-cn-0.22', 'en': 'vosk-model-small-en-us-0.15'}
MAX_DOWNLOAD = 96 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024


def provision(language, root=None):
    root = Path(root or Path(__file__).resolve().parent).resolve()
    models = root / 'models'
    models.mkdir(exist_ok=True)
    name = MODELS[language]
    destination = models / name
    if (destination / 'am' / 'final.mdl').is_file():
        print('Model is already installed:', destination)
        return destination
    if destination.exists():
        raise RuntimeError('Incomplete model directory exists. Rename it before retrying: ' + str(destination))
    url = 'https://alphacephei.com/vosk/models/' + name + '.zip'
    print('Downloading official model:', url, flush=True)
    with tempfile.TemporaryDirectory(prefix='download-', dir=models) as temporary:
        temp = Path(temporary).resolve()
        # TemporaryDirectory is always created inside the explicit models directory.
        temp.relative_to(models.resolve())
        archive = temp / 'model.zip'
        total = 0
        with urllib.request.urlopen(url, timeout=45) as response, archive.open('wb') as output:
            if not response.geturl().startswith('https://alphacephei.com/'):
                raise RuntimeError('Unexpected model download destination')
            while True:
                data = response.read(1024 * 1024)
                if not data:
                    break
                total += len(data)
                if total > MAX_DOWNLOAD:
                    raise RuntimeError('Model archive exceeded the size limit')
                output.write(data)
                print(f'Downloaded {total // (1024 * 1024)} MB', flush=True)
        with zipfile.ZipFile(archive) as zipped:
            if sum(entry.file_size for entry in zipped.infolist()) > MAX_EXPANDED:
                raise RuntimeError('Expanded model exceeded the size limit')
            for entry in zipped.infolist():
                path = PurePosixPath(entry.filename)
                mode = entry.external_attr >> 16
                if (path.is_absolute() or '..' in path.parts or '\\' in entry.filename
                        or ':' in entry.filename or not path.parts or path.parts[0] != name
                        or stat.S_ISLNK(mode)):
                    raise RuntimeError('Unsafe model archive member')
            zipped.extractall(temp)
        source = temp / name
        if not (source / 'am' / 'final.mdl').is_file() or not (source / 'conf').is_dir():
            raise RuntimeError('The model archive is incomplete')
        source.resolve().relative_to(models.resolve())
        destination.resolve().relative_to(models.resolve())
        shutil.move(str(source), str(destination))
    print('Installed:', destination)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Install a small Vosk model from its official publisher')
    parser.add_argument('language', nargs='?', choices=MODELS, default='zh')
    args = parser.parse_args()
    provision(args.language)
