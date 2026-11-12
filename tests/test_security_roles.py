"""Role assignments and document size stay bounded (GitLab #5).

An attribute qualifies every measure, so ``qualifies`` grows as attributes x
measures; role lists must not repeat a variable; and generation must stay near
linear in the number of variables.
"""

import json
import time

import pytest
from fastapi.testclient import TestClient

from ddicdi import editing
from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.cdi.jsonld import GenerateOptions, build_document
from ddicdi.config import settings
from ddicdi.data import Dataset
from ddicdi.models import DatasetMeta, Variable
from ddicdi.roles import MAX_ROLE_TEXT, parse_roles


def _meta(n: int) -> DatasetMeta:
    return DatasetMeta(
        variables=[Variable(name=f"v{i}", label=None, format="F8.2", storage_type="double", measure="scale",
                            numeric=True) for i in range(n)],
        number_rows=0,
        datafile="wide.csv",
        file_format="csv",
    )


def _csv(n_cols: int) -> bytes:
    header = ",".join(f"v{i}" for i in range(n_cols))
    row = ",".join("1" for _ in range(n_cols))
    return f"{header}\n{row}\n".encode()


@pytest.fixture()
def client(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    with TestClient(app) as c:
        yield c


# -- role lists ------------------------------------------------------------------------


def test_repeated_role_tokens_are_kept_once():
    meta = _meta(3)
    roles = parse_roles(meta, {"v1": ",".join(["attribute"] * 9)})
    assert roles.attribute == ["v1"]
    assert roles.measure == ["v0", "v2"]


def test_overlong_role_text_is_refused():
    meta = _meta(2)
    with pytest.raises(ValueError, match="longer than"):
        parse_roles(meta, {"v0": "attribute," * 1000})
    with pytest.raises(editing.EditError):
        editing.set_roles(meta, {"v0": "attribute," * 1000})


def test_set_role_lists_a_variable_once():
    meta = _meta(3)
    meta.roles.attribute = ["v1", "v1", "v1"]  # metadata saved before roles were deduplicated
    editing.ensure_roles(meta)
    assert meta.roles.attribute == ["v1"]
    editing._set_role(meta, "v1", "attribute, attribute ,ATTRIBUTE")
    assert meta.roles.attribute == ["v1"]


def test_failed_role_edit_leaves_roles_alone():
    meta = _meta(2)
    editing.ensure_roles(meta)
    with pytest.raises(editing.EditError):
        editing._set_role(meta, "v0", "nonsense")
    assert "v0" in meta.roles.measure


# -- budgets -----------------------------------------------------------------------------


def test_build_document_refuses_too_many_qualifies(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "max_qualifies_refs", 1000)
    meta = _meta(100)
    meta.roles = parse_roles(meta, {f"v{i}": "measure,attribute" for i in range(100)})
    with pytest.raises(ValueError, match="qualify every measure"):
        build_document(Dataset(meta, tmp_path / "data.csv"), options=GenerateOptions(max_rows=0))


def test_build_document_refuses_too_many_variables(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "max_variables", 50)
    meta = _meta(51)
    editing.ensure_roles(meta)
    with pytest.raises(ValueError, match="51 variables"):
        build_document(Dataset(meta, tmp_path / "data.csv"), options=GenerateOptions(max_rows=0))


def test_under_budget_document_still_has_qualifies(tmp_path):
    meta = _meta(4)
    meta.roles = parse_roles(meta, {"v0": "attribute"})
    doc = build_document(Dataset(meta, tmp_path / "data.csv"), options=GenerateOptions(max_rows=0))
    attr = next(e for e in doc["DDICDIModels"] if e["@type"] == "AttributeComponent")
    assert attr["qualifies"] == ["#measureComponent-v1", "#measureComponent-v2", "#measureComponent-v3"]


def test_api_rejects_cross_product_over_budget(client, monkeypatch):
    monkeypatch.setattr(settings, "max_qualifies_refs", 10_000)
    n = 2000  # 2000 x 1999 references, far over the budget
    roles = {f"v{i}": "measure,attribute" for i in range(n)}

    r = client.post(
        "/api/convert",
        files={"file": ("wide.csv", _csv(n))},
        data={"variable_roles": json.dumps(roles), "max_rows": "0"},
    )
    assert r.status_code == 400 and "qualify every measure" in r.json()["detail"]

    file_id = client.post("/api/files", files={"file": ("wide.csv", _csv(n))}).json()["file_id"]
    for fmt in ("ddicdi", "cdif"):
        r = client.post(f"/api/files/{file_id}/generate?format={fmt}", json={"roles": roles, "max_rows": 0})
        assert r.status_code == 400, (fmt, r.text)
    assert client.put(f"/api/files/{file_id}/roles", json={"roles": roles}).status_code == 200
    for fmt in ("ddicdi", "cdif"):
        r = client.post(f"/api/files/{file_id}/output?format={fmt}", json={"max_rows": 0})
        assert r.status_code == 400, (fmt, r.text)


def test_api_repeated_attribute_tokens_do_not_multiply(client):
    n = 50
    roles = {"v0": ",".join(["attribute"] * 9)}  # under the role-text limit, all repeats
    assert len(roles["v0"]) <= MAX_ROLE_TEXT
    file_id = client.post("/api/files", files={"file": ("wide.csv", _csv(n))}).json()["file_id"]
    r = client.post(f"/api/files/{file_id}/generate", json={"roles": roles, "max_rows": 0})
    assert r.status_code == 200, r.text
    attrs = [e for e in r.json()["DDICDIModels"] if e["@type"] == "AttributeComponent"]
    assert len(attrs) == 1 and len(attrs[0]["qualifies"]) == n - 1

    # thousands of repeated tokens are refused outright
    many = {"v0": ",".join(["attribute"] * 5000)}
    r = client.post(f"/api/files/{file_id}/generate", json={"roles": many, "max_rows": 0})
    assert r.status_code == 400 and "longer than" in r.json()["detail"]
    r = client.post("/api/convert", files={"file": ("wide.csv", _csv(n))},
                    data={"variable_roles": json.dumps(many)})
    assert r.status_code == 400
    assert client.put(f"/api/files/{file_id}/roles", json={"roles": many}).status_code == 400
    r = client.post(f"/api/files/{file_id}/variables", json={"name": "extra", "role": "attribute," * 5000})
    assert r.status_code == 400


# -- near-linear generation ------------------------------------------------------------------


def test_many_columns_generate_quickly(tmp_path):
    meta = _meta(5000)
    meta.roles = parse_roles(meta, {"v0": "identifier", "v1": "attribute"})
    start = time.perf_counter()
    doc = build_document(Dataset(meta, tmp_path / "data.csv"), options=GenerateOptions(max_rows=0))
    elapsed = time.perf_counter() - start
    assert len([e for e in doc["DDICDIModels"] if e["@type"] == "MeasureComponent"]) == 4998
    assert elapsed < 5, f"5000 columns took {elapsed:.1f}s"
