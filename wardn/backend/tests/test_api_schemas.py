from app.core.schemas import APIModel, to_camel_case


class ExampleAPIModel(APIModel):
    request_id: str
    input_usd_per_1m_tokens: int


def test_to_camel_case_preserves_numeric_segments() -> None:
    assert to_camel_case("input_usd_per_1m_tokens") == "inputUsdPer1mTokens"


def test_api_model_accepts_python_and_json_field_names() -> None:
    from_json = ExampleAPIModel.model_validate({"requestId": "json", "inputUsdPer1mTokens": 12})
    from_python = ExampleAPIModel(request_id="python", input_usd_per_1m_tokens=34)

    assert from_json.request_id == "json"
    assert from_python.request_id == "python"


def test_api_model_serializes_with_json_field_names() -> None:
    model = ExampleAPIModel(request_id="request", input_usd_per_1m_tokens=12)

    assert model.model_dump() == {"requestId": "request", "inputUsdPer1mTokens": 12}
