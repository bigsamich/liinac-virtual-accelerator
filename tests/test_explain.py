"""SPARK:AI:EXPLAIN: a general parameter-page explainer, not the VA assistant."""
import io
import json

from pip2va.analysis import assistant, llm


PAGE = ("Booster BPMs / Overview\n"
        "EP BOOSTER:BPM:DAQ_STATUS_21 = 0 Raw  crate 21 DAQ status\n"
        "AC B:DCCT = 2.98 E12  Description\n")


def _fake_ollama(monkeypatch, sent):
    def urlopen(req, timeout):
        sent.append(json.loads(req.data))
        return io.BytesIO(json.dumps(
            {"message": {"content": "crate 21 reads 0"}}).encode())
    monkeypatch.setattr(assistant.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(llm, "available", lambda *a, **k: True)


def test_explain_sends_the_page_and_question_under_its_own_prompt(monkeypatch):
    sent = []
    _fake_ollama(monkeypatch, sent)
    answer, engine = assistant.explain(PAGE, "why is crate 21 zero?")
    assert answer == "crate 21 reads 0" and engine.startswith("llm:")
    msgs = sent[0]["messages"]
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == assistant.EXPLAIN_SYSTEM
    assert "virtual accelerator" not in msgs[0]["content"]
    assert "under 200 words" in msgs[0]["content"]
    assert "PARAM PAGE HELP" in msgs[0]["content"]
    assert "never what value to set" in msgs[0]["content"]
    assert "User guide" in msgs[0]["content"]
    assert sent[0]["options"]["num_predict"] >= 900
    assert PAGE in msgs[1]["content"] and "why is crate 21 zero?" in msgs[1]["content"]
    assert "SNAPSHOT" not in msgs[1]["content"]


def test_explain_without_a_question_explains_the_page(monkeypatch):
    sent = []
    _fake_ollama(monkeypatch, sent)
    assistant.explain(PAGE, "")
    assert "Explain these lines" in sent[0]["messages"][1]["content"]


def test_explain_says_when_the_model_is_not_there(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda *a, **k: False)
    answer, engine = assistant.explain(PAGE, "")
    assert engine == "offline" and "not answering" in answer


def test_the_request_splits_page_and_question(monkeypatch):
    got = []
    monkeypatch.setattr(assistant, "explain", lambda p, q: got.append((p, q)) or ("", ""))
    assistant.explain_request(None, PAGE + "\n\nQUESTION: why?")
    assistant.explain_request(None, PAGE)
    assert got == [(PAGE, " why?"), (PAGE, "")]
