"""SPARK:AI:ANALYZE: a shift-log summary of a Plot window, not the VA assistant."""
import io
import json

from pip2va.analysis import assistant, llm


PLOT = ("Plot: Time view, 10m window 2026-11-15 14:00:00 to 14:10:00\n"
        "Trace 1: M:OUTTMP@p,1000 (Outdoor temperature) ACNET, DegF\n"
        "  n 600 at 1 Hz; latest 45.2; mean 45.0, sigma 0.12\n")


def _fake_ollama(monkeypatch, sent):
    def urlopen(req, timeout):
        sent.append(json.loads(req.data))
        return io.BytesIO(json.dumps(
            {"message": {"content": "steady at 45 DegF"}}).encode())
    monkeypatch.setattr(assistant.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(llm, "available", lambda *a, **k: True)


def test_analyze_sends_the_plot_under_its_own_prompt(monkeypatch):
    sent = []
    _fake_ollama(monkeypatch, sent)
    answer, engine = assistant.analyze(PLOT, "is it drifting?")
    assert answer == "steady at 45 DegF" and engine.startswith("llm:")
    msgs = sent[0]["messages"]
    system = msgs[0]["content"]
    assert system == assistant.ANALYZE_SYSTEM
    assert "shift-log" in system and "PLOT HELP" in system
    assert "never what value to set" in system and "under 200 words" in system
    assert "parameter page" not in system.lower()
    assert sent[0]["options"]["num_predict"] >= 900
    assert msgs[1]["content"].startswith("PLOT:\n" + PLOT)
    assert "is it drifting?" in msgs[1]["content"]


def test_analyze_without_a_question_summarises(monkeypatch):
    sent = []
    _fake_ollama(monkeypatch, sent)
    assistant.analyze(PLOT, "")
    assert "Summarise this plot" in sent[0]["messages"][1]["content"]


def test_the_analyze_request_splits_plot_and_question(monkeypatch):
    got = []
    monkeypatch.setattr(assistant, "analyze", lambda p, q: got.append((p, q)) or ("", ""))
    assistant.analyze_request(None, PLOT + "\n\nQUESTION: why?")
    assistant.analyze_request(None, PLOT)
    assert got == [(PLOT, " why?"), (PLOT, "")]


def test_the_gateway_serves_analyze():
    src = open("pip2va/services/epics_gateway/main.py").read()
    assert ":AI:ANALYZE" in src and "assistant.analyze_request" in src
