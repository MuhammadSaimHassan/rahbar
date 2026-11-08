import json

import pytest

from app.services.index_catalog import resolve_index


def test_bootstrap_and_published_collection_resolution():
    assert resolve_index("rahbar", None).generation == "bootstrap"
    active = resolve_index("rahbar", json.dumps({
        "collection": "rahbar-v-new", "generation": "a" * 32,
    }))
    assert active.collection == "rahbar-v-new" and active.generation == "a" * 32


@pytest.mark.parametrize("value", ["not json", '{}',
    '{"collection":"../other","generation":"bad"}',
    '{"collection":"valid-name","generation":"bad"}',
])
def test_invalid_catalog_fails_closed(value):
    with pytest.raises((ValueError, KeyError)):
        resolve_index("rahbar", value)
