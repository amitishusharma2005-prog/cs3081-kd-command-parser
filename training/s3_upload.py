"""Upload a trained model directory to bucket `models` under <version>/.

Needs S3_ENDPOINT, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY in the environment
(e.g. kubectl -n data port-forward svc/seaweedfs-s3 8333:8333, S3_ENDPOINT=http://localhost:8333).
Usage: python training/s3_upload.py v1
"""
import os
import sys

SKIP = {"model.sha256"}


def upload(version, model_dir=None):
    import boto3
    from botocore.config import Config
    model_dir = model_dir or os.path.join("models", version)
    s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], region_name="us-east-1",
                      config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"))
    for name in sorted(os.listdir(model_dir)):
        if name in SKIP:
            continue
        s3.upload_file(os.path.join(model_dir, name), "models", f"{version}/{name}")
        print(f"uploaded s3://models/{version}/{name}")


if __name__ == "__main__":
    upload(sys.argv[1])
