"""Example construction for sequence-level distillation (no torch import here)."""
import json

PROMPT_FMT = "Command: {text}\nJSON:"


def load_records(path, limit):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
            if len(rows) >= limit:
                break
    return rows


def build_example(tok, text, target, max_len):
    """Token ids + labels for `Command: <text>\\nJSON: <target><eos>`.

    Everything up to and including "JSON:" is masked with -100, so the loss is computed only on
    the JSON reply (starting at the space before "{") and the end-of-sequence token.
    """
    prefix = PROMPT_FMT.format(text=text)
    full = prefix + " " + target
    enc = tok(full, return_offsets_mapping=True, add_special_tokens=False)
    ids = list(enc["input_ids"]) + [tok.eos_token_id]
    labels = [-100 if end <= len(prefix) else i
              for i, (_, end) in zip(enc["input_ids"], enc["offset_mapping"])]
    labels.append(tok.eos_token_id)
    return ids[:max_len], labels[:max_len]


def smoke_tokenizer(texts):
    """Offline byte-level BPE used ONLY when the Hugging Face hub is unreachable (smoke runs)."""
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
    from transformers import PreTrainedTokenizerFast
    tk = Tokenizer(models.BPE())
    tk.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tk.decoder = decoders.ByteLevel()
    tk.train_from_iterator(texts, trainers.BpeTrainer(
        vocab_size=512, special_tokens=["<|endoftext|>"],
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    return PreTrainedTokenizerFast(tokenizer_object=tk, eos_token="<|endoftext|>", pad_token="<|endoftext|>")
