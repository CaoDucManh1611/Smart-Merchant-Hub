from app.core.config import settings
from app.api import recommendations
from app.auth.dependencies import require_admin_access
from app.services.recommendation_artifacts import RecommendationArtifactRegistry


def test_public_artifacts_are_discovered_but_disabled_by_default(tmp_path, monkeypatch):
    artifact = tmp_path / "unsupervised" / "uci_customer_segmentation.joblib"
    artifact.parent.mkdir()
    artifact.write_bytes(b"not loaded in this discovery test")
    monkeypatch.setattr(settings, "RECOMMENDATION_ARTIFACT_MODE", "fallback")
    registry = RecommendationArtifactRegistry(tmp_path)

    status = registry.status()
    assert "root" not in status
    entry = next(item for item in status["artifacts"] if item["key"] == "unsupervised_segmentation")
    assert entry["present"] is True
    assert entry["enabled"] is False
    assert entry["reason"] == "disabled_or_dataset_scope_mismatch"


def test_demo_artifact_requires_exact_known_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RECOMMENDATION_ARTIFACT_MODE", "demo")
    registry = RecommendationArtifactRegistry(tmp_path)
    path = tmp_path / "reinforcement" / "linucb_bandit_state.joblib"
    path.parent.mkdir()
    path.write_bytes(b"demo")

    assert registry.require_demo_artifact("reinforcement_policy") == path.resolve()


def test_artifact_status_endpoint_requires_admin_access():
    route = next(
        item
        for item in recommendations.router.routes
        if item.path == "/recommendations/artifacts"
    )
    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
    assert require_admin_access in dependency_calls
