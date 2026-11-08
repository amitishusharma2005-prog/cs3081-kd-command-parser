"""Runs inside the cluster (Job seed-buckets): create buckets, upload commands_pool.jsonl."""
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], region_name="us-east-1",
                      config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"))
for attempt in range(60):
    try:
        for b in ("datasets", "models"):
            try:
                s3.create_bucket(Bucket=b)
            except ClientError as e:
                if e.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    raise
        break
    except Exception as e:  # noqa: BLE001
        print("waiting for object storage:", e, flush=True)
        time.sleep(5)
else:
    raise SystemExit("object storage never became ready")
s3.upload_file("/pool/commands_pool.jsonl", "datasets", "commands_pool.jsonl")
print("buckets:", [b["Name"] for b in s3.list_buckets()["Buckets"]])
print("uploaded s3://datasets/commands_pool.jsonl")
