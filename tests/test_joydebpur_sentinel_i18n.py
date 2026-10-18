import json

import pytest
from PIL import Image

from src import i18n, sentinel
from src.geo_tools import polygon_metrics
from src.places import coverage, coverage_upazilas, in_coverage, locate
from src.verification_engine import MEANING


def test_coverage_is_joydebpur_focus_only():
    assert in_coverage(90.4231, 23.993) and in_coverage(90.4203, 23.9980)            # DV-011 area, Joydebpur junction
    assert not in_coverage(90.4146, 23.7925) and not in_coverage(90.2640, 23.8760)    # Gulshan (Dhaka), Savar
    assert not in_coverage(90.40, 24.10) and not in_coverage(88.36, 22.57)            # north Gazipur, Kolkata
    names = list(coverage_upazilas().shapeName)
    assert names == ["Joydebpur focus area"]
    hit = locate(90.4231, 23.993)
    assert hit["area_group"] == "Joydebpur"
    assert locate(90.2640, 23.8760)["upazila"] == "Savar"                              # lookup still works outside coverage


def test_every_demo_parcel_is_inside_joydebpur(con):
    from src import vdb
    for p in vdb.list_parcels(con):
        ring = json.loads(p["geometry_geojson"])["coordinates"][0][:-1]
        m = polygon_metrics([tuple(x) for x in ring])
        assert in_coverage(m["centroid"][1], m["centroid"][0]), p["parcel_id"]


def test_preplotted_data_is_joydebpur_only():
    from src import landmap
    s = landmap.stats()
    assert 20_000 < s["building"] < 60_000              # Joydebpur focus box, not Dhaka
    assert landmap.at_point(90.4146, 23.7925) == []     # Gulshan: outside the focus area, nothing pre-plotted


# ---------------------------------------------------------------- Sentinel-2
def test_window_is_at_least_500_m_and_centred():
    b = polygon_metrics([(90.4560, 23.8190), (90.4564, 23.8190), (90.4564, 23.8194), (90.4560, 23.8194)])["bounds"]
    w = sentinel.window_bbox(b)
    width_m = (w[2] - w[0]) * 111_320 * 0.915
    assert width_m >= 480 and (w[0] + w[2]) / 2 == pytest.approx((b[0] + b[2]) / 2, abs=1e-6)


def test_sentinel_failure_gives_a_readable_message_and_is_not_cached(monkeypatch):
    b = (90.4101, 23.8101, 90.4105, 23.8105)
    monkeypatch.setattr(sentinel, "_one_year", lambda bbox, year, cloud: None)
    hist, msg, bbox = sentinel.try_fetch_history(b)
    assert hist == [] and "No cloud-free Sentinel-2" in msg and "Traceback" not in msg and bbox is None
    ok = {"date": "2020-01-17", "date_kind": "capture", "image": Image.new("RGB", (50, 50)), "zoom": None, "resolution_m": 10.0, "provider": sentinel.PROVIDER, "cloud_cover": 0.0,
          "item_id": "x", "season": "Dec 2019 - Feb 2020"}
    monkeypatch.setattr(sentinel, "_one_year", lambda bbox, year, cloud: ok)
    hist, msg, bbox = sentinel.try_fetch_history(b)                                   # the earlier failure was not remembered
    assert len(hist) == len(sentinel.YEARS) and msg == "" and hist[0]["date_kind"] == "capture" and hist[0]["resolution_m"] == 10.0


def test_sentinel_unexpected_error_is_reported_not_raised(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internals")
    monkeypatch.setattr(sentinel, "_one_year", boom)
    hist, msg, _ = sentinel.try_fetch_history((90.4201, 23.8201, 90.4205, 23.8205))
    assert hist == [] and msg and "secret internals" not in msg


def test_tls_verification_is_never_switched_off(monkeypatch, tmp_path):
    import rasterio
    seen = {}
    monkeypatch.setattr(rasterio, "Env", lambda **kw: seen.update(kw))
    for v in ("CURL_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        monkeypatch.delenv(v, raising=False)
    sentinel._env()
    assert "GDAL_HTTP_UNSAFESSL" not in seen and "GDAL_HTTP_CAINFO" not in seen
    bundle = tmp_path / "ca.pem"
    bundle.write_text("x")
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    seen.clear()
    sentinel._env()
    assert seen["GDAL_HTTP_CAINFO"] == str(bundle) and "GDAL_HTTP_UNSAFESSL" not in seen


# ---------------------------------------------------------------- Bangla
def test_every_text_key_has_english_and_bangla():
    for k, (en, bn) in i18n.TEXT.items():
        assert en.strip() and bn.strip() and en != bn, k
        assert any("\u0980" <= ch <= "\u09ff" for ch in bn), f"{k}: no Bangla characters"


def test_statuses_and_all_check_titles_are_translated():
    assert set(i18n.STATUS) == {"PASS", "REVIEW_REQUIRED", "CONFLICT_FOUND", "UNAVAILABLE", "NOT_RUN"}
    assert set(i18n.CHECK_TITLES) == set(MEANING)                 # every engine check has a Bangla title
    assert set(i18n.OVERALL) == set(i18n.STATUS)


def test_language_switch(monkeypatch):
    monkeypatch.setattr(i18n, "lang", lambda: "bn")
    assert i18n.t("nav.verify") == "যাচাই" and "PASS" in i18n.status_text("PASS") and i18n.check_title("pending_cases", "x") == "চলমান মামলা"
    monkeypatch.setattr(i18n, "lang", lambda: "en")
    assert i18n.t("nav.verify") == "Verification" and i18n.status_text("PASS") == "PASS" and i18n.check_title("pending_cases", "Pending cases") == "Pending cases"
