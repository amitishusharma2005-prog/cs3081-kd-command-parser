"""Sequence-level knowledge distillation: fine-tune Pythia-70M on the teacher's JSON replies.

Reads ONLY training/config.yaml (plus SUBSET / VERSION environment variables or flags).
  python training/train.py                 # v1 on the first 1,500 cleaned records
  python training/train.py --subset 50     # smoke run (also: make train SUBSET=50)
  python training/train.py --version v2    # second model version (seed 43, 8 epochs)
"""
import argparse
import csv
import json
import os
import random
import sys

import numpy as np
import torch
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from package import build_archive  # noqa: E402

from data import build_example, load_records, smoke_tokenizer  # noqa: E402


def set_all_seeds(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    from transformers import set_seed
    set_seed(seed)


def load_model_and_tokenizer(cfg, texts):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    try:
        tok = AutoTokenizer.from_pretrained(cfg["base_model"])
        model = AutoModelForCausalLM.from_pretrained(cfg["base_model"])
        smoke = False
    except Exception as e:  # hub unreachable: keep `make train SUBSET=50` runnable offline
        print(f"WARNING: cannot load {cfg['base_model']} ({type(e).__name__}); using a tiny random "
              "SMOKE model. Its output must never be released or evaluated as the student.", file=sys.stderr)
        from transformers import GPTNeoXConfig, GPTNeoXForCausalLM
        tok = smoke_tokenizer(texts)
        model = GPTNeoXForCausalLM(GPTNeoXConfig(
            vocab_size=len(tok), hidden_size=64, num_hidden_layers=2, num_attention_heads=4,
            intermediate_size=256, max_position_embeddings=256,
            bos_token_id=tok.eos_token_id, eos_token_id=tok.eos_token_id))
        smoke = True
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return tok, model, smoke


def collate(batch, pad_id):
    n = max(len(ids) for ids, _ in batch)
    ids = torch.full((len(batch), n), pad_id, dtype=torch.long)
    lab = torch.full((len(batch), n), -100, dtype=torch.long)
    att = torch.zeros((len(batch), n), dtype=torch.long)
    for i, (x, y) in enumerate(batch):
        ids[i, :len(x)], lab[i, :len(y)], att[i, :len(x)] = torch.tensor(x), torch.tensor(y), 1
    return ids, att, lab


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="training/config.yaml")
    ap.add_argument("--subset", type=int, default=int(os.environ.get("SUBSET") or 0))
    ap.add_argument("--version", default=os.environ.get("VERSION") or "v1")
    a = ap.parse_args()
    with open(a.config) as f:
        cfg = yaml.safe_load(f)
    cfg.update(cfg["variants"][a.version])
    seed, epochs = cfg["seed"], cfg["epochs"]
    set_all_seeds(seed)
    n = min(a.subset, cfg["train_examples"]) if a.subset else cfg["train_examples"]
    records = load_records(cfg["train_file"], n)
    if not records:
        sys.exit(f"{cfg['train_file']} is empty or missing: run worker/clean.py first")
    tag = "subset" if a.subset else a.version
    out_dir = os.path.join("models", "_subset" if a.subset else a.version)
    tok, model, smoke = load_model_and_tokenizer(cfg, [f"Command: {r['text']}\nJSON: {r['target']}" for r in records])
    data = [build_example(tok, r["text"], r["target"], cfg["max_seq_length"]) for r in records]
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"])
    from transformers import get_linear_schedule_with_warmup
    steps = epochs * ((len(data) + cfg["batch_size"] - 1) // cfg["batch_size"])
    sched = get_linear_schedule_with_warmup(opt, int(cfg["warmup_ratio"] * steps), steps)
    gen = torch.Generator().manual_seed(seed)
    model.train()
    losses = []
    for epoch in range(1, epochs + 1):
        order = torch.randperm(len(data), generator=gen).tolist()
        tot, cnt = 0.0, 0
        for i in range(0, len(order), cfg["batch_size"]):
            ids, att, lab = collate([data[j] for j in order[i:i + cfg["batch_size"]]], tok.pad_token_id)
            out = model(input_ids=ids, attention_mask=att, labels=lab)
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            ntok = int((lab[:, 1:] != -100).sum())
            tot, cnt = tot + out.loss.item() * ntok, cnt + ntok
        losses.append(tot / max(cnt, 1))
        print(f"epoch {epoch}/{epochs} loss {losses[-1]:.4f}", flush=True)
    rows = [("epoch", "train_loss")] + [(i + 1, f"{v:.4f}") for i, v in enumerate(losses)]
    paths = [f"training/loss_{tag}.csv"] + ([] if a.version == "v2" and not a.subset else ["training/loss.csv"])
    for p in paths:
        with open(p, "w", newline="") as f:
            csv.writer(f).writerows(rows)
    os.makedirs(out_dir, exist_ok=True)
    model.save_pretrained(out_dir, safe_serialization=True)
    tok.save_pretrained(out_dir)
    info = {"model_version": a.version, "base_model": cfg["base_model"], "seed": seed, "epochs": epochs,
            "learning_rate": cfg["learning_rate"], "batch_size": cfg["batch_size"],
            "max_seq_length": cfg["max_seq_length"], "train_examples": len(records),
            "final_train_loss": round(losses[-1], 4), "smoke_fallback": smoke,
            "torch": torch.__version__}
    with open(os.path.join(out_dir, "version.json"), "w") as f:
        json.dump(info, f, indent=2)
    if smoke or a.subset:
        print(f"smoke/subset run finished; model in {out_dir} (not packaged or uploaded)")
        return
    archive = os.path.join("dist", f"model-{a.version}.tar.gz")
    digest = build_archive(out_dir, archive)
    with open(os.path.join(out_dir, "model.sha256"), "w") as f:
        f.write(f"{digest}  model-{a.version}.tar.gz\n")
    print(f"release asset {archive} sha256 {digest}")
    if os.environ.get("S3_ENDPOINT"):
        from s3_upload import upload
        upload(a.version)
    else:
        print("S3_ENDPOINT not set: skipped upload (run python training/s3_upload.py", a.version, ")")


if __name__ == "__main__":
    main()
