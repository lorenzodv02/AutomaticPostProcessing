# -*- coding: utf-8 -*-
"""
Test del provider DeepSeek per l'AI Vision (nessuna chiamata di rete).

Verifica il body della richiesta secondo la documentazione ufficiale
(api-docs.deepseek.com): endpoint OpenAI-compatibile, immagini come data-URL,
thinking mode con `reasoning_effort` + `thinking`, e fallback pulito al motore
esperto locale se la chiave manca o la chiamata fallisce.
"""

import io
import os
import shutil
import tempfile
import urllib.error
from unittest import mock

from analyzer import ai_vision_advisor as advisor

# 1x1 PNG trasparente: basta come "immagine" per costruire la richiesta
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _png(tmpdir):
    path = os.path.join(tmpdir, "vista.png")
    with open(path, "wb") as handle:
        handle.write(PNG_BYTES)
    return path


def _session():
    return {
        "cas_file": "synthetic.cas",
        "dat_file": "synthetic.dat",
        "assembly_type": "undertray",
        "physics_data": {
            "is_half_car_symmetric": False,
            "nodes_read": 4,
            "faces_read": 3,
            "summary_kpis": {"downforce_total_N": -150.0, "drag_total_N": 2.0},
            "pid_breakdown": [],
        },
    }


def _config(**extra):
    cfg = {
        "ai_vision": {
            "enabled": True,
            "provider": "deepseek",
            "model_deepseek": "deepseek-flash",
            "deepseek_thinking": True,
            "deepseek_reasoning_effort": "high",
            "api_key": "test-key",
            "language": "it",
        }
    }
    cfg["ai_vision"].update(extra)
    return cfg


def test_payload_carries_vision_and_thinking():
    folder = tempfile.mkdtemp(prefix="ds_img_")
    try:
        payload = advisor.build_deepseek_payload(
            _config()["ai_vision"], "contesto reale", [_png(folder)]
        )
        assert payload["model"] == "deepseek-flash"
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["reasoning_effort"] == "high"
        assert payload["stream"] is False
        # in thinking mode temperatura e penalty non sono ammesse: non vanno inviate
        for banned in ("temperature", "presence_penalty", "frequency_penalty"):
            assert banned not in payload

        assert [m["role"] for m in payload["messages"]] == ["system", "user"]
        blocks = payload["messages"][1]["content"]
        assert blocks[0]["type"] == "text"
        image_block = blocks[1]
        assert image_block["type"] == "image_url"
        assert image_block["image_url"]["url"].startswith("data:image/png;base64,")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_payload_thinking_can_be_disabled():
    payload = advisor.build_deepseek_payload(
        _config(deepseek_thinking=False)["ai_vision"], "contesto", []
    )
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload


def test_payload_invalid_effort_falls_back_to_high():
    payload = advisor.build_deepseek_payload(
        _config(deepseek_reasoning_effort="ultra")["ai_vision"], "contesto", []
    )
    assert payload["reasoning_effort"] == "high"


def test_extract_answer_reads_content_and_reasoning():
    body = {
        "choices": [
            {"message": {"content": "risposta", "reasoning_content": "ragionamento"}}
        ]
    }
    assert advisor.extract_deepseek_answer(body) == ("risposta", "ragionamento")
    assert advisor.extract_deepseek_answer({}) == ("", "")
    assert advisor.extract_deepseek_answer({"choices": []}) == ("", "")


def test_without_api_key_uses_local_engine():
    result = advisor.generate_ai_vision_commentary(
        _config(api_key=""), _session(), {}, [], []
    )
    assert "Motore Diagnostico" in result["source"]
    assert result["commentary_markdown"]
    status = result["ai_status"]
    assert status["mode"] == "local"
    assert "API key" in status["reason"], status


def test_deepseek_success_reports_model_and_thinking():
    body = {"choices": [{"message": {"content": "perizia DeepSeek", "reasoning_content": "x"}}]}
    with mock.patch.object(advisor, "deepseek_ask", return_value=body) as called:
        result = advisor.generate_ai_vision_commentary(
            _config(), _session(), {}, [], []
        )
    assert called.called
    payload = called.call_args[0][1]
    assert payload["model"] == "deepseek-flash"
    assert "DeepSeek Vision" in result["source"]
    assert "thinking high" in result["source"]
    assert result["commentary_markdown"] == "perizia DeepSeek"
    status = result["ai_status"]
    assert status["mode"] == "ai"
    assert status["provider"] == "deepseek"
    assert status["model"] == "deepseek-flash"
    assert status["reason"] == ""


def test_http_error_falls_back_and_lists_models():
    error = urllib.error.HTTPError(
        "https://api.deepseek.com/chat/completions", 400, "Bad Request", {},
        io.BytesIO(b'{"error":"model not found"}'),
    )
    with mock.patch.object(advisor, "deepseek_ask", side_effect=error), \
         mock.patch.object(advisor, "deepseek_available_models",
                           return_value=["deepseek-flash", "deepseek-v4-pro"]):
        result = advisor.generate_ai_vision_commentary(
            _config(model_deepseek="modello-sbagliato"), _session(), {}, [], []
        )
    assert "Motore Diagnostico" in result["source"]
    status = result["ai_status"]
    assert status["mode"] == "local"
    assert "HTTP 400" in status["reason"], status


def test_unknown_provider_falls_back_to_gemini():
    """Un provider scritto male non deve rompere la pipeline."""
    config = _config()
    config["ai_vision"]["provider"] = "chatgpt"
    config["ai_vision"]["api_key"] = ""
    result = advisor.generate_ai_vision_commentary(config, _session(), {}, [], [])
    assert "Motore Diagnostico" in result["source"]


def test_image_data_url_detects_mime():
    folder = tempfile.mkdtemp(prefix="ds_img_")
    try:
        path = os.path.join(folder, "foto.jpg")
        with open(path, "wb") as handle:
            handle.write(b"\xff\xd8\xff\xe0")
        assert advisor.image_data_url(path).startswith("data:image/jpeg;base64,")
    finally:
        shutil.rmtree(folder, ignore_errors=True)

def test_disabled_ai_reports_reason():
    """Con l'AI disattivata il report deve dire il motivo, non solo 'motore locale'."""
    result = advisor.generate_ai_vision_commentary(
        _config(enabled=False, api_key="chiave-finta"), _session(), {}, [], []
    )
    assert result["ai_status"]["mode"] == "local"
    assert "disattivata" in result["ai_status"]["reason"], result["ai_status"]
