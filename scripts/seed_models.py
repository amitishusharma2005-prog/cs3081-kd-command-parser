"""Runs inside the cluster (Job seed-models): fetch GitHub Release model assets, verify SHA-256,
unpack and store them in bucket `models` under v1/ and v2/."""
import hashlib
import io
import os
import tarfile
import urllib.request

import boto3
from botocore.config import Config

BASE = os.environ["RELEASE_BASE"]
s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], region_name="us-east-1",
                      config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"))
for version in ("v1", "v2"):
    expected = open(f"/checksums/{version}.sha256").read().split()[0]
    data = urllib.request.urlopen(f"{BASE}/model-{version}.tar.gz", timeout=300).read()
    got = hashlib.sha256(data).hexdigest()
    if got != expected:
        raise SystemExit(f"{version}: checksum mismatch {got} != {expected}")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            if m.isfile():
                s3.put_object(Bucket="models", Key=f"{version}/{m.name}", Body=tar.extractfile(m).read())
                print(f"stored s3://models/{version}/{m.name}")
