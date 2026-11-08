"""Deterministic release archive + SHA-256 for a model directory."""
import gzip
import hashlib
import io
import os
import tarfile

SKIP = {"model.sha256"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_archive(model_dir, out_path):
    """tar.gz with sorted entries, zeroed mtimes/owners: same files -> same bytes."""
    names = sorted(n for n in os.listdir(model_dir) if n not in SKIP)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for n in names:
            p = os.path.join(model_dir, n)
            info = tar.gettarinfo(p, arcname=n)
            info.mtime, info.uid, info.gid, info.uname, info.gname, info.mode = 0, 0, 0, "", "", 0o644
            with open(p, "rb") as f:
                tar.addfile(info, f)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        gz.write(buf.getvalue())
    return sha256_file(out_path)
