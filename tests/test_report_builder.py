# -*- coding: utf-8 -*-
"""Lo slider velocita' nel report deve essere autonomo e coerente."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reporting.report_builder import _build_speed_estimator  # noqa: E402


def test_speed_estimator_embeds_reference_values():
    html, css, js = _build_speed_estimator(14.0, 483.0, 222.7)
    assert html and css and js
    assert 'id="speed-slider"' in html
    assert "14.0" in html
    assert "483 N" in html
    assert "222.7 N" in html
    for element in ("speed-df", "speed-drag", "speed-ld", "speed-power", "speed-factor"):
        assert 'id="%s"' % element in html, element


def test_speed_estimator_js_scales_with_square():
    _html, _css, js = _build_speed_estimator(12.5, 400.0, 200.0)
    assert "12.5" in js
    # (v/BASE)^2 e non una proporzionalita' lineare
    assert "(v / BASE) * (v / BASE)" in js
    assert "addEventListener" in js
    # nessun placeholder rimasto
    assert "__" not in js and "__" not in _html


def test_speed_estimator_disabled_without_valid_reference():
    assert _build_speed_estimator(0.0, 1.0, 1.0) == ("", "", "")
    assert _build_speed_estimator("x", 1.0, 1.0) == ("", "", "")
