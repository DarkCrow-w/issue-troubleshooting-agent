"""Check evidence references after Pydantic validates the response shape."""


def validate_references(value, valid_ids: set[str]):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("evidence_ids", "counter_evidence_ids", "evidence_requests"):
                if not set(item).issubset(valid_ids):
                    raise ValueError("模型引用了不存在的证据")
            elif key == "evidence_id" and item not in valid_ids:
                raise ValueError("模型引用了不存在的证据")
            validate_references(item, valid_ids)
    elif isinstance(value, list):
        for item in value:
            validate_references(item, valid_ids)
