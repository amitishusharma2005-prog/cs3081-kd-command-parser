"""Command-parser inference service (port 8000).

Configuration (environment): MODEL_URI (s3://models/v1/), MODEL_VERSION, S3_ENDPOINT, MAX_NEW_TOKENS,
and FAULT_INJECT (1 -> replace the model output with "not json" before validation).
S3 credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) arrive from a Kubernetes Secret.
"""
import json
import os
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

SCHEMA_PATH = os.environ.get("SCHEMA_PATH") or str(Path(__file__).resolve().parent.parent / "data" / "schema.json")
with open(SCHEMA_PATH, encoding="utf-8") as _f:
    _SCHEMA = json.load(_f)
KEYS = _SCHEMA["keys"]
INTENTS = set(_SCHEMA["intents"])

STATE = {"ready": False, "model": None, "tokenizer": None, "error": None}
GEN_LOCK = threading.Semaphore(1)  # one generation at a time per pod: keeps health probes responsive


def download_model(model_uri, endpoint, dest):
    import boto3
    from botocore.config import Config
    assert model_uri.startswith("s3://"), "MODEL_URI must look like s3://bucket/prefix/"
    bucket, _, prefix = model_uri[5:].partition("/")
    prefix = prefix.rstrip("/") + "/"
    s3 = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1",
                      config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"))
    n = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            name = obj["Key"][len(prefix):]
            if name:
                s3.download_file(bucket, obj["Key"], os.path.join(dest, name))
                n += 1
    print(f"downloaded {n} files from {model_uri}", flush=True)
    if n == 0:
        raise RuntimeError(f"no objects under {model_uri}")


def load_model():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    torch.set_num_threads(1)
    dest = tempfile.mkdtemp(prefix="model-")
    download_model(os.environ["MODEL_URI"], os.environ["S3_ENDPOINT"], dest)
    STATE["tokenizer"] = AutoTokenizer.from_pretrained(dest)
    STATE["model"] = AutoModelForCausalLM.from_pretrained(dest).eval()
    STATE["ready"] = True
    print("model ready", flush=True)


def _load_in_background():
    try:
        load_model()
    except Exception as e:  # stay alive (healthz 200) but never become ready
        STATE["error"] = repr(e)
        print(f"model load failed: {e!r}", flush=True)


@asynccontextmanager
async def lifespan(_app):
    if os.environ.get("SKIP_MODEL_LOAD") != "1":
        threading.Thread(target=_load_in_background, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)


def generate(text):
    import torch
    tok, model = STATE["tokenizer"], STATE["model"]
    enc = tok(f"Command: {text}\nJSON:", return_tensors="pt")
    with torch.no_grad():
        out = model.generate(**enc, max_new_tokens=int(os.environ.get("MAX_NEW_TOKENS", "96")),
                             do_sample=False, pad_token_id=tok.eos_token_id)
    return tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def validate_output(raw):
    """Return the 4-key dict if `raw` satisfies schema.json, else None."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict) or set(obj) != set(KEYS) or obj["intent"] not in INTENTS:
        return None
    if any(obj[k] is not None and not isinstance(obj[k], str) for k in ("date", "time", "place")):
        return None
    return {k: obj[k] for k in KEYS}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    if STATE["ready"]:
        return {"status": "ready"}
    return JSONResponse({"status": "loading"}, status_code=503)


@app.post("/parse")
def parse(body: dict):
    text = body.get("text")
    if not isinstance(text, str):
        return JSONResponse({"error": "text must be a string"}, status_code=422)
    if not STATE["ready"]:
        return JSONResponse({"status": "loading"}, status_code=503)
    with GEN_LOCK:
        raw = generate(text)
    if os.environ.get("FAULT_INJECT") == "1":
        raw = "not json"
    obj = validate_output(raw)
    if obj is None:
        return JSONResponse({"error": "invalid_model_output"}, status_code=500)
    headers = {"X-Model-Version": os.environ.get("MODEL_VERSION", ""),
               "X-Served-By": os.environ.get("POD_NAME") or os.environ.get("HOSTNAME", "")}
    return JSONResponse(obj, status_code=200, headers=headers)
