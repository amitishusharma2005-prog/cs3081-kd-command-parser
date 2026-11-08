"""Raw outputs + score.py report for one model on data/validation.jsonl.

  python training/evaluate.py --mode teacher   --name teacher          (Ollama phi3.5, same prompt/settings)
  python training/evaluate.py --mode untrained --name untrained        (EleutherAI/pythia-70m, no training)
  python training/evaluate.py --mode student --model-dir models/v1 --name student_v1
Writes results/<name>_predictions.jsonl and results/<name>_validation.json.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "worker"))


def causal_lm_generator(path, max_new_tokens=96):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForCausalLM.from_pretrained(path).eval()

    def gen(text):
        enc = tok(f"Command: {text}\nJSON:", return_tensors="pt")
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False,
                                 pad_token_id=tok.eos_token_id)
        return tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    return gen


def teacher_generator():
    from teacher import ask_teacher, load_prompt
    template = load_prompt()
    return lambda text: ask_teacher(template, text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["teacher", "untrained", "student"], required=True)
    ap.add_argument("--model-dir")
    ap.add_argument("--name", required=True)
    ap.add_argument("--gold", default="data/validation.jsonl")
    ap.add_argument("--max-new-tokens", type=int, default=96)
    a = ap.parse_args()
    if a.mode == "teacher":
        gen = teacher_generator()
    elif a.mode == "untrained":
        gen = causal_lm_generator("EleutherAI/pythia-70m", a.max_new_tokens)
    else:
        gen = causal_lm_generator(a.model_dir, a.max_new_tokens)
    os.makedirs("results", exist_ok=True)
    pred_path, rep_path = f"results/{a.name}_predictions.jsonl", f"results/{a.name}_validation.json"
    with open(a.gold, encoding="utf-8") as g, open(pred_path, "w", encoding="utf-8") as out:
        for line in g:
            if line.strip():
                rec = json.loads(line)
                out.write(json.dumps({"id": rec["id"], "prediction": gen(rec["text"])}) + "\n")
    subprocess.run([sys.executable, "tools/score.py", pred_path, a.gold, "--out", rep_path], check=True)


if __name__ == "__main__":
    main()
