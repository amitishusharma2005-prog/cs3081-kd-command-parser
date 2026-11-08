"""Shared teacher call: phi3.5 served by Ollama, temperature 0, seed 42."""
import os
import time

import requests

MODEL = "phi3.5"
OPTIONS = {"temperature": 0, "seed": 42, "num_predict": 150, "stop": ["\nCommand:"], "num_gpu": 0}


def load_prompt(path=None):
    path = path or os.environ.get("PROMPT_PATH", "prompts/teacher_prompt.txt")
    with open(path, encoding="utf-8") as f:
        return f.read()


def ask_teacher(template, command, url=None, retries=8):
    """Return the teacher's exact reply text for one command."""
    url = (url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
    body = {"model": MODEL, "prompt": template.replace("{command}", command),
            "stream": False, "format": "json", "options": OPTIONS}
    for attempt in range(retries):
        try:
            r = requests.post(f"{url}/api/generate", json=body, timeout=300)
            r.raise_for_status()
            return r.json()["response"]
        except (requests.RequestException, KeyError, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
