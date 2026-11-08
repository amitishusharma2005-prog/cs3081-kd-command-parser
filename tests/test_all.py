import importlib.util
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTENTS = set(json.load(open(os.path.join(ROOT, "data", "schema.json")))["intents"])


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


clean = _load("clean_mod", "worker/clean.py")
svc = _load("service_app", "service/app.py")
nacl = _load("nacl_mod", "tools/nacl_sim.py")
score = _load("score_mod", "tools/score.py")


def rec(i, text, raw):
    return {"id": f"C{i:04d}", "text": text, "teacher_raw": raw if isinstance(raw, str) else json.dumps(raw)}


GOOD = {"intent": "weather_query", "date": None, "time": None, "place": "london"}


# ---------- worker/clean.py: rules (a)-(e) ----------
def test_clean_each_rule_counted_once():
    recs = [
        rec(1, "what is the weather in london", GOOD),                                              # kept
        rec(2, "what is the weather in paris", "not json at all"),                                  # (a)
        rec(3, "what is the weather in rome", "[1, 2]"),                                            # (a) not an object
        rec(4, "what is the weather in oslo", {"intent": "weather_query", "place": "oslo"}),        # (b)
        rec(5, "what is the weather in nice", {**GOOD, "intent": "make_coffee"}),                   # (c)
        rec(6, "what is the weather in kyiv", {**GOOD, "place": "Kyiv City"}),  # (d)
        rec(7, "what is the weather in london", GOOD),  # duplicate of 1
        rec(8, "what is the weather in bern", {**GOOD, "place": "BERN"}),                           # kept
    ]
    kept, c = clean.clean_records(recs, INTENTS)
    assert (c["a"], c["b"], c["c"], c["d"], c["duplicates"], c["kept"]) == (2, 1, 1, 1, 1, 2)
    assert c["input"] == c["a"] + c["b"] + c["c"] + c["d"] + c["duplicates"] + c["kept"]
    assert [r["id"] for r in kept] == ["C0001", "C0008"]


def test_clean_duplicate_keeps_smallest_id_even_if_input_unsorted():
    recs = [rec(9, "set an alarm", {**GOOD, "intent": "alarm_set", "place": None}),
            rec(3, "set an alarm", {**GOOD, "intent": "alarm_set", "place": None})]
    kept, c = clean.clean_records(recs, INTENTS)
    assert [r["id"] for r in kept] == ["C0003"] and c["duplicates"] == 1


def test_clean_slot_rules_non_string_and_empty():
    recs = [rec(1, "what is the weather", {**GOOD, "place": 5}), rec(2, "what is the weather", {**GOOD, "place": ""})]
    _, c = clean.clean_records(recs, INTENTS)
    assert c["d"] == 2 and c["kept"] == 0


# ---------- service/app.py ----------
@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("MODEL_VERSION", "v1")
    monkeypatch.setenv("POD_NAME", "pod-abc")
    monkeypatch.delenv("FAULT_INJECT", raising=False)
    svc.STATE["ready"] = False
    with TestClient(svc.app) as c:
        yield c
    svc.STATE["ready"] = False


def test_healthz_ok_even_while_loading(client):
    r = client.get("/healthz")
    assert r.status_code == 200


def test_readyz_503_until_loaded_then_200(client):
    assert client.get("/readyz").status_code == 503
    svc.STATE["ready"] = True
    assert client.get("/readyz").status_code == 200


def test_parse_valid_returns_only_four_keys_and_headers(client, monkeypatch):
    svc.STATE["ready"] = True
    monkeypatch.setattr(svc, "generate", lambda text: json.dumps(GOOD))
    r = client.post("/parse", json={"text": "what is the weather in london"})
    assert r.status_code == 200 and r.json() == GOOD
    assert list(r.json()) == ["intent", "date", "time", "place"]
    assert r.headers["X-Model-Version"] == "v1" and r.headers["X-Served-By"] == "pod-abc"


@pytest.mark.parametrize("bad", ["not json", '{"intent": "alarm_set"}', json.dumps({**GOOD, "intent": "nope"}),
                                 json.dumps({**GOOD, "date": 3}), '{"intent": "alarm_set", "date": "to']
                         )
def test_parse_invalid_model_output_is_500(client, monkeypatch, bad):
    svc.STATE["ready"] = True
    monkeypatch.setattr(svc, "generate", lambda text: bad)
    r = client.post("/parse", json={"text": "x"})
    assert r.status_code == 500 and r.json() == {"error": "invalid_model_output"}


def test_fault_inject_forces_500(client, monkeypatch):
    svc.STATE["ready"] = True
    monkeypatch.setattr(svc, "generate", lambda text: json.dumps(GOOD))
    monkeypatch.setenv("FAULT_INJECT", "1")
    r = client.post("/parse", json={"text": "x"})
    assert r.status_code == 500 and r.text.replace(" ", "") == '{"error":"invalid_model_output"}'


# ---------- tools/nacl_sim.py with network/nacl.json ----------
def _decide(direction, port, addr, proto="tcp"):
    rules = nacl.load_rules(os.path.join(ROOT, "network", "nacl.json"))
    return nacl.decide(rules, {"direction": direction, "protocol": proto, "port": port, "address": addr})[0]


@pytest.mark.parametrize("args,expected", [
    (("inbound", 443, "203.0.113.7"), "allow"), (("inbound", 80, "203.0.113.7"), "allow"),
    (("inbound", 80, "198.51.100.200"), "deny"), (("inbound", 443, "198.51.100.1"), "deny"),
    (("inbound", 22, "10.20.5.130"), "allow"), (("inbound", 22, "203.0.113.7"), "deny"),
    (("inbound", 22, "10.20.5.20"), "deny"), (("inbound", 40000, "10.20.2.9"), "allow"),
    (("inbound", 40000, "203.0.113.7"), "deny"), (("inbound", 80, "203.0.113.7", "udp"), "deny"),
    (("outbound", 8000, "10.20.1.1"), "allow"), (("outbound", 8000, "10.20.1.1", "udp"), "deny"),
    (("outbound", 50000, "203.0.113.7"), "allow"), (("outbound", 443, "203.0.113.7"), "deny"),
    (("outbound", 22, "10.20.5.130"), "deny"),
])
def test_nacl_decisions(args, expected):
    assert _decide(*args) == expected


def test_nacl_sample_packets_all_correct():
    out = subprocess.run([sys.executable, "tools/nacl_sim.py", "network/nacl.json", "network/packets_sample.jsonl",
                          "--check"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert "Correct: 6 / 6" in out


# ---------- tools/score.py ----------
def test_score_perfect_and_broken():
    gold = [{"id": "V1", "text": "t", **GOOD}, {"id": "V2", "text": "t", **GOOD}]
    preds = [{"id": "V1", "prediction": json.dumps(GOOD)}, {"id": "V2", "prediction": '{"intent": "weather_q'}]
    rep = score.score(preds, gold)
    assert rep["json_validity"] == 50.0 and rep["full_frame"] == 50.0


# ---------- training/data.py: prompt masking ----------
def test_prompt_tokens_are_masked():
    pytest.importorskip("transformers")
    import data
    tok = data.smoke_tokenizer(["Command: hello world\nJSON: " + json.dumps(GOOD)] * 4)
    ids, labels = data.build_example(tok, "hello world", json.dumps(GOOD), 128)
    assert len(ids) == len(labels) and labels[-1] == tok.eos_token_id
    assert labels[0] == -100
    decoded_target = tok.decode([t for t in labels if t != -100])
    assert decoded_target.strip() == json.dumps(GOOD) + tok.eos_token
    assert "Command" not in decoded_target
