"""Structural validation in addition to existing semantic publication validators."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator


def validate_sidecar_schema(value, name):
    if name not in {'game-predictor', 'matchup-intelligence'}:
        raise ValueError('Unknown artifact schema')
    schema = json.loads((Path(__file__).parent / 'schemas' / (name + '.schema.json')).read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
