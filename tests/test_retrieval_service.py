from __future__ import annotations

from pathlib import Path

import pytest

from mcp_servers.principia_retrieval.retrieval_service import PrincipiaRetrievalService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TUTORIALS_ROOT = PROJECT_ROOT.parent / "blastFoam_tutorials"


@pytest.fixture()
def service(monkeypatch: pytest.MonkeyPatch) -> PrincipiaRetrievalService:
    monkeypatch.setenv("BLASTFOAM_TUTORIALS", str(TUTORIALS_ROOT))
    for variable in (
        "LLM_API_KEY",
        "RETRIEVAL_LLM_API_KEY",
        "RETRIEVAL_LLM_ACTIVE_PROFILE",
        "PRINCIPIA_MODEL_PROFILE",
    ):
        monkeypatch.delenv(variable, raising=False)
    return PrincipiaRetrievalService()


def test_status_loads_bundled_knowledge_graph(service: PrincipiaRetrievalService) -> None:
    status = service.get_status()

    assert status["project_root"] == str(PROJECT_ROOT)
    assert status["case_nodes"] > 0
    assert status["case_relationships"] > 0
    assert "blastXiFoam/deflagrationToDetonationTransition" in status["known_cases"]


def test_case_alias_and_file_lookup_are_deterministic(service: PrincipiaRetrievalService) -> None:
    case = service.get_case_by_intent("Configure a DDT case")
    assert case["found"] is True
    assert case["case_path"] == "blastXiFoam/deflagrationToDetonationTransition"

    files = service.get_files_for_case(case["case_path"])
    paths = {item["file_path"] for item in files["files"]}
    assert "system/controlDict" in paths
    assert "constant/combustionProperties" in paths


def test_candidate_then_detail_contract(service: PrincipiaRetrievalService) -> None:
    candidates = service.search_case_content(
        query="change the endTime and write interval",
        case_path="blastFoam/freeField",
        top_k=2,
    )

    assert candidates["found"] is True
    assert candidates["detail_level"] == "candidates"
    first = candidates["results"][0]
    assert first["file_path"] == "system/controlDict"
    assert first["result_id"].startswith("case_file:")

    detail = service.search_case_content(
        detail_level="detail",
        result_id=first["result_id"],
    )
    assert detail["found"] is True
    assert detail["file_path"] == "system/controlDict"
    assert "application" in detail["content"]


def test_user_guide_search_has_offline_lexical_fallback(service: PrincipiaRetrievalService) -> None:
    result = service.search_user_guide("Runge Kutta time integration", top_k=3)

    assert result["found"] is True
    assert result["detail_level"] == "candidates"
    assert all("content" not in item for item in result["results"])


def test_file_content_lookup_rejects_path_traversal(service: PrincipiaRetrievalService) -> None:
    result = service.get_file_content(
        "blastFoam/freeField",
        "../../../../etc/passwd",
    )

    assert result["found"] is False
    assert result["content"].startswith("File access denied outside BLASTFOAM_TUTORIALS")
