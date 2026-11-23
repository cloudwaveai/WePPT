"""Install pinned, bundled skill distributions locally. No remote code or install hooks."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'vendor' / 'skills'
DEST = ROOT / 'data' / 'upstream-skills'

def install():
    manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8'))
    for package in manifest['packages']:
        archive = SOURCE / package['archive']
        if hashlib.sha256(archive.read_bytes()).hexdigest() != package['sha256']:
            raise ValueError('Bundled skill checksum mismatch: ' + package['id'])
        target = DEST / package['id'] / package['commit']
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                path = (target / member.filename).resolve()
                if not path.is_relative_to(target.resolve()):
                    raise ValueError('Archive path outside package')
                if member.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(bundle.read(member))
        (target / '.weppt-installed.json').write_text(json.dumps(package), encoding='utf-8')
        print(json.dumps({'id': package['id'], 'files': package['files'], 'installed': True}))

if __name__ == '__main__':
    install()
