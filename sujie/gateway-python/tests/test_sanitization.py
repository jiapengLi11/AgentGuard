import pytest
from sujie_gateway.sanitization import extract_public_ipv4_iocs, render_public_ipv4_iocs


def test_public_ipv4_extraction_has_strict_output_allowlist():
    source = "8.8.8.8 10.1.2.3 999.1.2.3 1.1.1.1 224.0.0.1 8.8.8.8 user8.8.8.8"
    addresses = extract_public_ipv4_iocs(source)
    assert addresses == ("1.1.1.1", "8.8.8.8")
    assert render_public_ipv4_iocs(addresses) == "PUBLIC_IPV4_IOCS\n1.1.1.1\n8.8.8.8"


def test_public_ipv4_extraction_fails_closed_on_unbounded_or_empty_source():
    with pytest.raises(ValueError, match="INVALID_IOC_SOURCE"):
        extract_public_ipv4_iocs("x" * 1_000_001)
    with pytest.raises(ValueError, match="NO_PUBLIC_IOCS"):
        render_public_ipv4_iocs(extract_public_ipv4_iocs("10.1.2.3 only"))
