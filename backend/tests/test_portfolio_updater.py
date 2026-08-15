import json
import pytest
from app.portfolio.updater import PortfolioUpdater
from app.schemas.contracts import PortfolioPatch

def test_add_skill_is_idempotent():
    files={"data/skills.json":json.dumps(["Python"])}
    patch=PortfolioPatch.model_validate({"operations":[{"type":"add_skill","skill":"Python"}]})
    writes=PortfolioUpdater().materialize(patch,lambda p:files.get(p,""))
    assert json.loads(writes["data/skills.json"]) == ["Python"]
def test_mapping_blocks_unrelated_project():
    patch=PortfolioPatch.model_validate({"operations":[{"type":"update_project","project_id":"other","changes":{"description":"x"}}]})
    with pytest.raises(ValueError): PortfolioUpdater().validate(patch,"mapped")
def test_secret_blocks_portfolio_content():
    patch=PortfolioPatch.model_validate({"operations":[{"type":"update_project","project_id":"x","changes":{"description":"token=supersecretvalue"}}]})
    with pytest.raises(ValueError): PortfolioUpdater().materialize(patch,lambda _:"{}")
