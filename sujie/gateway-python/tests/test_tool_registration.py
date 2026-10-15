import sys
from pathlib import Path

import pytest
from mcp import StdioServerParameters
from sujie_gateway.m1_runtime import StdioMCPProxy

ROOT = Path(__file__).resolve().parents[2]
POISONED = ROOT / "mcp-servers/malicious-variants/tool_poisoned.py"
SCHEMA_POISONED = ROOT / "mcp-servers/malicious-variants/schema_poisoned.py"
CATALOG_FIXTURE = ROOT / "mcp-servers/eval-catalog-fixture/server.py"


@pytest.mark.asyncio
async def test_tool_description_injection_is_rejected_before_registration():
    params = {"poisoned": StdioServerParameters(command=sys.executable, args=[str(POISONED)])}
    with pytest.raises(RuntimeError, match="TOOL_METADATA_INJECTION"):
        async with StdioMCPProxy(params):
            pytest.fail("poisoned tool must not become available")


@pytest.mark.asyncio
async def test_schema_description_injection_is_rejected_before_registration():
    params = {
        "poisoned": StdioServerParameters(command=sys.executable, args=[str(SCHEMA_POISONED)])
    }
    with pytest.raises(RuntimeError, match="TOOL_METADATA_INJECTION"):
        async with StdioMCPProxy(params):
            pytest.fail("poisoned schema must not become available")


@pytest.mark.asyncio
async def test_unexpected_tool_addition_is_rejected_before_registration(tmp_path):
    description = tmp_path / "description.txt"
    description.write_text("Search for a query.", "utf-8")
    params = {
        "fixture": StdioServerParameters(
            command=sys.executable,
            args=[str(CATALOG_FIXTURE)],
            env={
                "SUJIE_CATALOG_DESCRIPTION_FILE": str(description),
                "SUJIE_CATALOG_EXTRA_NAME": "search_advanced",
                "SUJIE_CATALOG_EXTRA_DESCRIPTION_FILE": str(description),
            },
        )
    }
    approved = {"fixture": frozenset({"search"})}
    proxy = StdioMCPProxy(params, expected_tools=approved)
    approved["fixture"] = frozenset({"search", "search_advanced"})
    with pytest.raises(RuntimeError, match="TOOL_CATALOG_DRIFT"):
        async with proxy:
            pytest.fail("unexpected tool must not become available")


@pytest.mark.asyncio
async def test_pinned_clean_catalog_is_admitted(tmp_path):
    description = tmp_path / "description.txt"
    description.write_text("Search for a query.", "utf-8")
    params = {
        "fixture": StdioServerParameters(
            command=sys.executable,
            args=[str(CATALOG_FIXTURE)],
            env={"SUJIE_CATALOG_DESCRIPTION_FILE": str(description)},
        )
    }
    async with StdioMCPProxy(params, expected_tools={"fixture": frozenset({"search"})}) as proxy:
        assert set(proxy.registry) == {"fixture.search"}
