"""Read private rule judgments; no source-business findings are bundled."""
from pathlib import Path
import json


def load_details(path):
    data = json.loads(Path(path).expanduser().resolve().read_text())
    if not isinstance(data, dict):
        raise ValueError('Private rule judgments must be grouped by role and source-rule key')
    for role, records in data.items():
        if not isinstance(role, str) or not isinstance(records, dict):
            raise ValueError('Invalid private role/rule judgment map')
        for key, value in records.items():
            if (not isinstance(value, dict) or set(value) != {'reason', 'selectors'}
                    or not isinstance(value['reason'], str) or not isinstance(value['selectors'], list)):
                raise ValueError('A private judgment requires reason and explicit source selectors')
    return data
