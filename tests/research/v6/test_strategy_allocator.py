from quant_trading_system.research.v6.strategy_allocator import audit_allocator_inputs


def record(name: str, role: str, decision: str) -> dict[str, object]:
    return {
        "research_id": name,
        "lane": name[0],
        "role": role,
        "decision": decision,
        "monthly_path": f"{name}_monthly.parquet",
        "holdings_path": f"{name}_holdings.parquet",
    }


def test_rejected_inputs_cannot_fill_required_roles() -> None:
    audit = audit_allocator_inputs(
        [
            record("A", "index_enhancement", "SHADOW_BASELINE"),
            record("B", "defensive", "REJECTED"),
            record("C", "independent_alpha", "REJECTED"),
        ]
    )
    assert audit["status"] == "DATA_BLOCKED"
    assert audit["missing_roles"] == ["defensive", "independent_alpha"]
    assert audit["eligible_count"] == 1


def test_three_eligible_roles_pass() -> None:
    audit = audit_allocator_inputs(
        [
            record("A", "index_enhancement", "SHADOW_BASELINE"),
            record("B", "defensive", "SHADOW"),
            record("C", "independent_alpha", "PROMOTE_TO_LIVE_SHADOW"),
        ]
    )
    assert audit["status"] == "PASS"
    assert audit["missing_roles"] == []


def test_missing_evidence_field_fails_closed() -> None:
    broken = record("A", "index_enhancement", "SHADOW_BASELINE")
    broken.pop("holdings_path")
    audit = audit_allocator_inputs([broken])
    assert audit["status"] == "DATA_BLOCKED"
    assert audit["invalid_inputs"]
