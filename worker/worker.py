"""Teacher-labelling worker.

Takes the commands whose 0-based line number i satisfies i % SHARD_COUNT == SHARD_INDEX,
asks the teacher for each, and writes datasets/teacher/shard-<SHARD_INDEX>.jsonl to object
storage. Progress is checkpointed so a restarted pod resumes instead of starting over.
"""
import json
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from teacher import ask_teacher, load_prompt

CHECKPOINT_EVERY = 50


def s3_client():
    return boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], region_name="us-east-1",
                        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4",
                                      retries={"max_attempts": 15, "mode": "standard"},
                                      connect_timeout=10, read_timeout=120))


def read_lines(s3, bucket, key):
    try:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    except ClientError:
        return []
    return [line for line in body.splitlines() if line.strip()]


def select_shard(commands, shard_index, shard_count):
    return [c for i, c in enumerate(commands) if i % shard_count == shard_index]


def main():
    shard_index = int(os.environ["SHARD_INDEX"])
    shard_count = int(os.environ["SHARD_COUNT"])
    s3 = s3_client()
    commands = [json.loads(x) for x in read_lines(s3, "datasets", "commands_pool.jsonl")]
    mine = select_shard(commands, shard_index, shard_count)
    out_key = f"teacher/shard-{shard_index}.jsonl"
    done = read_lines(s3, "datasets", out_key)
    seen = {json.loads(x)["id"] for x in done}
    template = load_prompt()
    print(f"shard {shard_index}/{shard_count}: {len(mine)} commands, {len(seen)} already done", flush=True)
    lines = list(done)
    for n, rec in enumerate(mine, 1):
        if rec["id"] in seen:
            continue
        raw = ask_teacher(template, rec["text"])
        lines.append(json.dumps({"id": rec["id"], "text": rec["text"], "teacher_raw": raw}, ensure_ascii=False))
        if n % CHECKPOINT_EVERY == 0:
            s3.put_object(Bucket="datasets", Key=out_key, Body=("\n".join(lines) + "\n").encode())
            print(f"checkpoint {n}/{len(mine)}", flush=True)
    s3.put_object(Bucket="datasets", Key=out_key, Body=("\n".join(lines) + "\n").encode())
    print(f"done: wrote s3://datasets/{out_key} ({len(lines)} lines)", flush=True)


if __name__ == "__main__":
    main()
