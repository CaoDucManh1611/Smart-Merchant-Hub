import pytest

from app.services.image_observation_cache import (
    clear_image_observation_cache,
    get_image_observation,
    image_cache_key,
    put_image_observation,
)


def setup_function():
    clear_image_observation_cache()


def test_cache_is_tenant_model_kind_and_image_scoped_and_expires():
    base = dict(image_bytes=b"image-one", model_version="vision:v1", analysis_kind="catalog")
    key = image_cache_key(business_id=1, **base)
    assert key != image_cache_key(business_id=2, **base)
    assert key != image_cache_key(business_id=1, **{**base, "model_version": "vision:v2"})
    assert key != image_cache_key(business_id=1, **{**base, "image_bytes": b"image-two"})

    value = {"matched_sku": "A-1", "candidate_skus": ["A-1"]}
    put_image_observation(key, value, ttl_seconds=10, max_entries=2, now=100)
    loaded = get_image_observation(key, now=105)
    assert loaded == value
    loaded["matched_sku"] = "tampered"
    assert get_image_observation(key, now=105)["matched_sku"] == "A-1"
    assert get_image_observation(key, now=110) is None


def test_cache_is_bounded_and_rejects_invalid_scope():
    for index in range(3):
        put_image_observation(str(index), {"value": index}, ttl_seconds=10,
                              max_entries=2, now=100)
    assert get_image_observation("0", now=101) is None
    assert get_image_observation("1", now=101) == {"value": 1}
    with pytest.raises(ValueError):
        image_cache_key(business_id=0, image_bytes=b"x", model_version="m", analysis_kind="k")
