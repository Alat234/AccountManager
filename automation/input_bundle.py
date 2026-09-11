"""Private, stable upload copies prepared before a task enters the worker queue."""
import hashlib
import shutil
import tempfile
from pathlib import Path
from storage.atomic_files import write_json


def prepare_uploads(groups, root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    bundle = Path(tempfile.mkdtemp(prefix='rk-', dir=root))
    copied, manifest = {}, {}
    try:
        for name, paths in groups.items():
            copied[name], manifest[name] = [], []
            for index, source in enumerate(paths):
                source = Path(source)
                destination = bundle / name / str(index) / source.name
                destination.parent.mkdir(parents=True)
                before = source.stat()
                shutil.copyfile(source, destination)
                after = source.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError('Upload document changed during preparation')
                digest = hashlib.sha256(destination.read_bytes()).hexdigest()
                copied[name].append(destination)
                manifest[name].append({'file': str(destination.relative_to(bundle)), 'sha256': digest})
        write_json(bundle / 'manifest.json', manifest)
        return copied
    except Exception:
        # Only the newly created private directory can be removed here.
        if bundle.resolve().is_relative_to(root.resolve()):
            shutil.rmtree(bundle)
        raise
