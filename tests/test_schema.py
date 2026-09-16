import json
from importlib.resources import files


def test_schema_is_packaged_and_versioned():
    schema = json.loads(files('framecleave').joinpath('schemas/scene-index-v1.json').read_text())
    assert schema['properties']['schema_version']['const'] == 1
    assert schema['properties']['interval_semantics']['const'] == 'decoded-frames-half-open'
    assert {'source', 'timeline', 'scenes', 'boundaries'} <= set(schema['required'])
