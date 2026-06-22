from app.modules.mcp_runtime import adapter_contract


def test_adapter_url_joins_endpoint_and_path() -> None:
    assert adapter_contract.adapter_url("http://runtime:8000/", "/mcp") == (
        "http://runtime:8000/mcp"
    )
