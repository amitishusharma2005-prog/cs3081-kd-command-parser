"""Clean the teacher shard outputs into datasets/v1/train.jsonl (+ SHA-256).

Records are sorted by id, then every record gets exactly one verdict, so
input = (a) + (b) + (c) + (d) + duplicates + kept.
  (a) reply is not valid JSON (or not a JSON object)
  (b) keys are not exactly intent, date, time, place
  (c) intent is not one of the eight
  (d) a slot is neither null nor non-empty text that appears in the command
  (e) duplicate command text (the smallest id is kept)

Usage: python worker/clean.py [--shards 'datasets/teacher/shard-*.jsonl'] [--out datasets/v1]
       Set S3_ENDPOINT (+ AWS_* credentials) to read the shards from the bucket instead.
"""
import argparse
import glob
import hashlib
import json
import os

KEYS = {"intent", "date", "time", "place"}
SLOTS = ("date", "time", "place")


def load_intents(schema_path="data/schema.json"):
    with open(schema_path, encoding="utf-8") as f:
        return set(json.load(f)["intents"])


def judge(record, intents):
    """Return (verdict, parsed). verdict is 'a'..'d' or 'ok'."""
    try:
        parsed = json.loads(record["teacher_raw"])
    except (json.JSONDecodeError, TypeError):
        return "a", None
    if not isinstance(parsed, dict):
        return "a", None
    if set(parsed.keys()) != KEYS:
        return "b", None
    if parsed["intent"] not in intents:
        return "c", None
    text = record["text"].lower()
    for s in SLOTS:
        v = parsed[s]
        if v is None:
            continue
        if not isinstance(v, str) or not v.strip() or v.lower() not in text:
            return "d", None
    return "ok", parsed


def clean_records(records, intents):
    records = sorted(records, key=lambda r: r["id"])
    counts = {"input": len(records), "a": 0, "b": 0, "c": 0, "d": 0, "duplicates": 0, "kept": 0}
    seen, kept = set(), []
    for rec in records:
        verdict, parsed = judge(rec, intents)
        if verdict != "ok":
            counts[verdict] += 1
            continue
        key = rec["text"].strip().lower()
        if key in seen:
            counts["duplicates"] += 1
            continue
        seen.add(key)
        target = json.dumps({k: parsed[k] for k in ("intent", "date", "time", "place")}, ensure_ascii=False)
        kept.append({"id": rec["id"], "text": rec["text"], "teacher_raw": rec["teacher_raw"], "target": target})
    counts["kept"] = len(kept)
    assert counts["input"] == sum(counts[k] for k in ("a", "b", "c", "d", "duplicates", "kept"))
    return kept, counts


def read_shards(pattern):
    records = []
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as f:
            records += [json.loads(x) for x in f if x.strip()]
    return records


def read_shards_s3():
    import boto3
    from botocore.config import Config
    s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], region_name="us-east-1",
                        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"))
    records = []
    for obj in s3.list_objects_v2(Bucket="datasets", Prefix="teacher/shard-").get("Contents", []):
        body = s3.get_object(Bucket="datasets", Key=obj["Key"])["Body"].read().decode("utf-8")
        records += [json.loads(x) for x in body.splitlines() if x.strip()]
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", default="datasets/teacher/shard-*.jsonl")
    ap.add_argument("--out", default="datasets/v1")
    ap.add_argument("--schema", default="data/schema.json")
    a = ap.parse_args()
    records = read_shards_s3() if os.environ.get("S3_ENDPOINT") else read_shards(a.shards)
    if not records:
        raise SystemExit("no shard records found: run the teacher workers first (make label)")
    ids = [r["id"] for r in records]
    if len(ids) != len(set(ids)):
        raise SystemExit("an id appears in more than one shard output")
    kept, counts = clean_records(records, load_intents(a.schema))
    os.makedirs(a.out, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept).encode("utf-8")
    with open(os.path.join(a.out, "train.jsonl"), "wb") as f:
        f.write(body)
    digest = hashlib.sha256(body).hexdigest()
    with open(os.path.join(a.out, "train.sha256"), "w") as f:
        f.write(f"{digest}  train.jsonl\n")
    with open(os.path.join(a.out, "clean_report.json"), "w") as f:
        json.dump(counts, f, indent=2)
    print(json.dumps(counts, indent=2))
    print("sha256", digest)


if __name__ == "__main__":
    main()
