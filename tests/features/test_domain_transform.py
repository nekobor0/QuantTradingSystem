from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.features import *
from quant_trading_system.features.errors import InvalidFeature, SnapshotPurposeMismatch

NOW = datetime(2024, 1, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize("direction", [-2, 0, 2])
def test_definition_direction_must_be_signed(direction):
    with pytest.raises(InvalidFeature): FeatureDefinition("x", FeaturePurpose.ETF_TIMING, FormulaKind.MOMENTUM, "m", direction, "1d", "o")


@pytest.mark.parametrize("field", ["name", "economic_meaning", "frequency", "owner"])
def test_definition_requires_text(field):
    values = dict(name="x", purpose=FeaturePurpose.ETF_TIMING, formula=FormulaKind.MOMENTUM, economic_meaning="m", direction=1, frequency="1d", owner="o")
    values[field] = ""
    with pytest.raises(InvalidFeature): FeatureDefinition(**values)


@pytest.mark.parametrize("min_history", [0, -1])
def test_version_history_positive(min_history):
    with pytest.raises(InvalidFeature): FeatureVersion(uuid4(), "1", "c", {}, {}, min_history, MissingPolicy.REJECT)


@pytest.mark.parametrize("field", ["version", "code_version"])
def test_version_requires_identity(field):
    values = dict(definition_id=uuid4(), version="1", code_version="c", parameters={}, dependency_versions={}, min_history=1, missing_policy=MissingPolicy.REJECT)
    values[field] = ""
    with pytest.raises(InvalidFeature): FeatureVersion(**values)


def test_observation_requires_aware_time():
    with pytest.raises(InvalidFeature): InputObservation(uuid4(), "close", date.today(), NOW.replace(tzinfo=None), Decimal(1), "r", uuid4())


@pytest.mark.parametrize("field_name,source_ref", [("", "r"), ("close", "")])
def test_observation_requires_identity(field_name, source_ref):
    with pytest.raises(InvalidFeature): InputObservation(uuid4(), field_name, date.today(), NOW, Decimal(1), source_ref, uuid4())


def test_diagnostic_cannot_enter_production_domain():
    with pytest.raises(InvalidFeature): FeatureDiagnostic(uuid4(), date.today(), "IC", Decimal(".1"), False)


@pytest.mark.parametrize("purpose", list(FeaturePurpose))
def test_purpose_roundtrip(purpose): assert FeaturePurpose(purpose.value) is purpose


@pytest.mark.parametrize("formula", list(FormulaKind))
def test_formula_roundtrip(formula): assert FormulaKind(formula.value) is formula


@pytest.mark.parametrize("policy", list(MissingPolicy))
def test_missing_policy_roundtrip(policy): assert MissingPolicy(policy.value) is policy


@pytest.mark.parametrize("transform", list(TransformKind))
def test_transform_roundtrip(transform): assert TransformKind(transform.value) is transform


def test_wrong_purpose_binding_rejected(repository):
    service = FeatureService(repository)
    definition = FeatureDefinition("x", FeaturePurpose.ETF_TIMING, FormulaKind.MOMENTUM, "m", 1, "1d", "o")
    version = FeatureVersion(definition.definition_id, "1", "c", {"window":"1"}, {}, 2, MissingPolicy.REJECT)
    service.register(definition, (version,))
    with pytest.raises(SnapshotPurposeMismatch): service.bind_required(FeaturePurpose.EQUITY_DAILY_SELECTION, (version.version_id,))


def test_empty_binding_rejected(repository):
    with pytest.raises(InvalidFeature): FeatureService(repository).bind_required(FeaturePurpose.ETF_TIMING, ())


def test_winsor_zscore_records_steps(repository):
    service = FeatureService(repository)
    definition = FeatureDefinition("roe-z", FeaturePurpose.EQUITY_DAILY_SELECTION, FormulaKind.ROE, "quality", 1, "1d", "o")
    version = FeatureVersion(definition.definition_id, "1", "c", {"winsor_lower":"0", "winsor_upper":"1"}, {}, 1, MissingPolicy.REJECT, TransformKind.WINSOR_ZSCORE)
    service.register(definition, (version,)); service.bind_required(definition.purpose, (version.version_id,))
    members = (uuid4(), uuid4(), uuid4()); universe = UniverseSnapshotInput(uuid4(), definition.purpose, members, "h"); data_id = uuid4()
    observations = tuple(InputObservation(i, "roe", date(2024,1,10), NOW, Decimal(v), f"r{v}", data_id) for i,v in zip(members, (1,2,100)))
    result = service.calculate_feature_set(CalculateFeatureSet(definition.purpose, (version.version_id,), date(2024,1,10), NOW, universe, data_id, observations))
    rows = service.get_feature_matrix(result.feature_set_id)[1]
    assert len(rows) == 3 and all("zscore" in rows[0].steps[-1] for _ in [0])


def test_zero_variance_transform_rejected(repository):
    service = FeatureService(repository)
    definition = FeatureDefinition("roe-z", FeaturePurpose.EQUITY_DAILY_SELECTION, FormulaKind.ROE, "quality", 1, "1d", "o")
    version = FeatureVersion(definition.definition_id, "1", "c", {"winsor_lower":"0", "winsor_upper":"1"}, {}, 1, MissingPolicy.REJECT, TransformKind.WINSOR_ZSCORE)
    service.register(definition, (version,)); service.bind_required(definition.purpose, (version.version_id,))
    members=(uuid4(),uuid4()); universe=UniverseSnapshotInput(uuid4(),definition.purpose,members,"h");data_id=uuid4();obs=tuple(InputObservation(i,"roe",date(2024,1,10),NOW,Decimal(1),"r",data_id) for i in members)
    from quant_trading_system.features.errors import FeatureCalculationRejected
    with pytest.raises(FeatureCalculationRejected): service.calculate_feature_set(CalculateFeatureSet(definition.purpose,(version.version_id,),date(2024,1,10),NOW,universe,data_id,obs))

