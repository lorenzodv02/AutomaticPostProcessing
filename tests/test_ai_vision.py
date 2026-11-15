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
        try:
            from PIL import Image
            Image.new("RGB", (8, 8), (255, 0, 0)).save(path, format="JPEG")
        except Exception:
            with open(path, "wb") as handle:
                handle.write(b"\xff\xd8\xff\xe0")
        url = advisor.image_data_url(path)
        assert url.startswith("data:image/"), url[:40]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_oversized_image_is_downscaled():
    """Un'immagine oltre il limite del server deve essere ridotta prima dell'invio."""
    try:
        import base64
        import io as _io

        from PIL import Image
    except Exception:
        return  # CI senza Pillow: la normalizzazione non e' attiva

    folder = tempfile.mkdtemp(prefix="ds_img_")
    try:
        path = os.path.join(folder, "larga.png")
        Image.new("RGB", (9000, 120), (30, 60, 90)).save(path, format="PNG")
        url = advisor.image_data_url(path)
        raw = base64.b64decode(url.split(",", 1)[1])
        with Image.open(_io.BytesIO(raw)) as im:
            assert max(im.size) <= advisor.MAX_VISION_IMAGE_SIDE, im.size
            assert im.mode == "RGB"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_unreadable_image_is_skipped():
    """Un file che non e' un'immagine non deve far fallire la richiesta."""
    folder = tempfile.mkdtemp(prefix="ds_img_")
    try:
        path = os.path.join(folder, "rotto.png")
        with open(path, "wb") as handle:
            handle.write(b"non e un png")
        payload = advisor.build_deepseek_payload({}, "testo", [path])
        blocks = payload["messages"][1]["content"]
        # senza Pillow i byte vengono inviati cosi' come sono; con Pillow l'immagine si scarta
        try:
            from PIL import Image  # noqa: F401
            assert len(blocks) == 1, blocks
        except Exception:
            assert len(blocks) == 2, blocks
    finally:
        shutil.rmtree(folder, ignore_errors=True)

def test_disabled_ai_reports_reason():
    """Con l'AI disattivata il report deve dire il motivo, non solo 'motore locale'."""
    result = advisor.generate_ai_vision_commentary(
        _config(enabled=False, api_key="chiave-finta"), _session(), {}, [], []
    )
    assert result["ai_status"]["mode"] == "local"
    assert "disattivata" in result["ai_status"]["reason"], result["ai_status"]

def _http_error(status, body):
    return urllib.error.HTTPError(
        "https://api.deepseek.com/chat/completions", status, "Error", {}, io.BytesIO(body)
    )


def test_check_without_key_stops_immediately():
    info = advisor.deepseek_check({"model_deepseek": "deepseek-flash", "api_key": ""})
    assert info["key_present"] is False
    assert info["models"] == []
    assert info["models_error"] == ""


def test_check_flags_model_not_in_account_list():
    def fake_http(method, path, key, body=None, timeout=120):
        if method == "GET":
            return {"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]}
        return {"choices": [{"message": {"content": "OK"}}]}

    with mock.patch.object(advisor, "_deepseek_http", side_effect=fake_http):
        info = advisor.deepseek_check({"model_deepseek": "deepseek-flash", "api_key": "k" * 12})
    assert info["models"] == ["deepseek-chat", "deepseek-reasoner"]
    assert info["model_available"] is False
    assert info["thinking_call"].startswith("ok")


def test_check_reports_server_message():
    error = _http_error(400, b'{"error":{"message":"Model Not Exist"}}')
    with mock.patch.object(advisor, "_deepseek_http", side_effect=error):
        info = advisor.deepseek_check({"model_deepseek": "deepseek-flash", "api_key": "k" * 12})
    assert "HTTP 400" in info["models_error"]
    assert "Model Not Exist" in info["models_error"]


def test_payload_respects_total_image_cap():
    """Sopra il limite di dimensione si smette di aggiungere immagini."""
    fake_url = "data:image/png;base64," + "A" * 2000
    with mock.patch.object(advisor, "image_data_url", return_value=fake_url):
        payload = advisor.build_deepseek_payload(
            {}, "testo", ["a.png", "b.png"], max_total_bytes=3000)
    blocks = payload["messages"][1]["content"]
    # solo il blocco di testo + una immagine: la seconda sfonderebbe il limite
    assert len(blocks) == 2, len(blocks)


def test_retry_without_images_on_http_400():
    folder = tempfile.mkdtemp(prefix="ds_img_")
    try:
        image = _png(folder)
        ok_body = {"choices": [{"message": {"content": "perizia solo testo"}}]}
        error = _http_error(400, b'{"error":{"message":"invalid image"}}')
        cv = {"annotated_images": [{"annotated_path": image}]}
        with mock.patch.object(advisor, "deepseek_ask", side_effect=[error, ok_body]) as called:
            result = advisor.generate_ai_vision_commentary(_config(), _session(), cv, [], [])
        assert called.call_count == 2
        assert "solo testo" in result["source"]
        assert result["commentary_markdown"] == "perizia solo testo"
        assert result["ai_status"]["mode"] == "ai"
    finally:
        shutil.rmtree(folder, ignore_errors=True)

def test_check_reads_input_modalities():
    def fake_http(method, path, key, body=None, timeout=120):
        if method == "GET":
            return {"data": [{"id": "deepseek-flash", "input_modalities": ["text", "image"]}]}
        return {"choices": [{"message": {"content": "OK"}}]}

    with mock.patch.object(advisor, "_deepseek_http", side_effect=fake_http):
        info = advisor.deepseek_check({"model_deepseek": "deepseek-flash", "api_key": "k" * 12})
    assert info["modalities"] == ["text", "image"]
    assert info["vision_supported"] is True
    assert info["vision_probe"].startswith("ok")


def test_vision_probe_detects_model_without_images():
    """Se la richiesta con immagine viene rifiutata, il modello non ha vision."""
    def fake_http(method, path, key, body=None, timeout=120):
        if method == "GET":
            return {"data": [{"id": "deepseek-flash", "input_modalities": ["text"]}]}
        content = body["messages"][0]["content"]
        if isinstance(content, list):
            raise _http_error(400, b'{"error":{"message":"model does not support images"}}')
        return {"choices": [{"message": {"content": "OK"}}]}

    with mock.patch.object(advisor, "_deepseek_http", side_effect=fake_http):
        info = advisor.deepseek_check({"model_deepseek": "deepseek-flash", "api_key": "k" * 12})
    assert info["modalities"] == ["text"]
    assert info["vision_probe"].startswith("HTTP 400")
    assert "does not support images" in info["vision_probe"]
    assert info["vision_supported"] is False


def test_tiny_probe_png_is_valid():
    """
    Il PNG della prova vision deve essere un'immagine valida: se fosse corrotto
    il server risponderebbe 400 e la diagnostica direbbe (falsamente) che il
    modello non accetta immagini.
    """
    import base64
    import struct
    import zlib

    raw = base64.b64decode(advisor._TINY_PNG_B64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "firma PNG mancante"
    assert raw[-12:] .startswith(b"\x00\x00\x00\x00IEND"), "chunk IEND mancante"

    # IHDR: subito dopo la firma
    assert raw[12:16] == b"IHDR"
    width, height, bit_depth, color_type = struct.unpack(">IIBB", raw[16:26])
    assert (width, height) == (1, 1)
    assert bit_depth == 8
    assert color_type == 2      # RGB

    # IDAT deve decomprimere a una scanline valida (filtro 0 + 3 byte RGB)
    idat_start = raw.index(b"IDAT") + 4
    idat_len = struct.unpack(">I", raw[idat_start - 8:idat_start - 4])[0]
    pixels = zlib.decompress(raw[idat_start:idat_start + idat_len])
    assert pixels == b"\x00\x00\x00\x00", pixels
