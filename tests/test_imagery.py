import numpy as np
import pytest
from PIL import Image

from src import wayback as wb
from src.real_analysis import compare_real, comparison_warnings, real_anomalies


def chip(green=0.2, res=1.09, mask_on=True, color=(120, 140, 90)):
    arr = np.full((60, 80, 3), color, np.uint8)
    mask = np.zeros((60, 80), np.uint8)
    if mask_on:
        mask[10:40, 10:50] = 1
    return {"date": "2024-01-01", "raw": Image.fromarray(arr), "mask": mask, "poly_px": [(10, 10), (50, 10), (50, 40), (10, 40)],
            "greenness": green, "resolution_m": res}


def test_missing_vegetation_values_do_not_crash_and_are_reported():
    a, b = chip(green=None), chip(green=0.1)
    r = compare_real(a, b)
    assert r["greenness_change"] is None
    assert any("vegetation measurement is missing" in w for w in r["warnings"])
    assert compare_real(chip(green=0.2), chip(green=None))["greenness_change"] is None
    assert real_anomalies({"changed_pct_plot": None, "greenness_change": None}) == []


def test_resolution_mismatch_and_empty_mask_are_disclosed():
    w = comparison_warnings(chip(res=1.09), chip(res=0.27))
    assert any("different resolutions" in x for x in w)
    w2 = comparison_warnings(chip(), chip(mask_on=False))
    assert any("does not cover any pixels" in x for x in w2)
    assert comparison_warnings(chip(), chip()) == []


def test_identical_images_show_no_change_inside_the_polygon():
    r = compare_real(chip(), chip())
    assert r["changed_pct_plot"] == 0.0 and r["greenness_change"] == 0.0


def test_network_failure_gives_a_readable_message_not_a_stack_trace(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("simulated network failure")
    monkeypatch.setattr(wb, "_get", boom)
    monkeypatch.setattr(wb, "CACHE", tmp_path)          # no on-disk catalogue to fall back to
    monkeypatch.setattr(wb, "_RELEASES", [])
    hist, msg = wb.try_fetch_history((90.1111, 23.9111, 90.1121, 23.9121), (90.1116, 23.9116))
    assert hist == [] and "internet" in msg.lower() and "Traceback" not in msg


def test_timeout_is_handled(tmp_path, monkeypatch):
    import socket
    def slow(*a, **k):
        raise socket.timeout("timed out")
    monkeypatch.setattr(wb, "_get", slow); monkeypatch.setattr(wb, "CACHE", tmp_path); monkeypatch.setattr(wb, "_RELEASES", [])
    hist, msg = wb.try_fetch_history((90.2111, 23.8111, 90.2121, 23.8121), (90.2116, 23.8116))
    assert hist == [] and msg


def test_too_large_vs_download_failure_messages(monkeypatch):
    fake = [{"date": "2024-01-01", "url": "http://example.invalid/{level}/{row}/{col}"}]
    monkeypatch.setattr(wb, "_distinct_versions", lambda lon, lat: fake)
    monkeypatch.setattr(wb, "best_chip", lambda url, bbox: (None, None))
    _, small = wb.try_fetch_history((90.3001, 23.7001, 90.3011, 23.7011), (90.3006, 23.7006))
    assert "could not be downloaded" in small
    _, big = wb.try_fetch_history((90.0, 23.5, 90.4, 23.9), (90.2, 23.7))
    assert "too large" in big


def test_empty_history_failures_are_not_remembered(monkeypatch):
    calls = {"n": 0}
    fake = [{"date": "2024-01-01", "url": "u"}]
    monkeypatch.setattr(wb, "_distinct_versions", lambda lon, lat: fake)
    def flaky(url, bbox):
        calls["n"] += 1
        return (None, None) if calls["n"] == 1 else (Image.new("RGB", (40, 40)), 17)
    monkeypatch.setattr(wb, "best_chip", flaky)
    bbox, centre = (90.4001, 23.8001, 90.4011, 23.8011), (90.4006, 23.8006)
    assert wb.try_fetch_history(bbox, centre)[0] == []                              # first call fails
    assert len(wb.try_fetch_history(bbox, centre)[0]) == 1                          # second call retries (failure was not cached)


def test_padded_bbox_and_area_helpers():
    bb = wb.padded_bbox((90.40, 23.80, 90.41, 23.81))
    assert bb[0] < 90.40 and bb[2] > 90.41
    w, h = wb.area_km((90.0, 23.0, 90.1, 23.1), 23.05)
    assert 9 < w < 11.5 and 10 < h < 12
