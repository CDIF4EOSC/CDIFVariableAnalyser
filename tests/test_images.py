"""Image collections: upload, bundle inheritance, staged AI description, CDIF and zip."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ddicdi.api.main import create_app
from ddicdi.config import settings
from ddicdi.images import describe as ai
from ddicdi.images.collection import ImageStore
from ddicdi import qlever
from ddicdi.images.media import ImageRejected, process
from ddicdi.qlever import cdif_graph, shacl_check

LICENCE = "https://creativecommons.org/licenses/by/4.0/"


def picture(fmt: str = "JPEG", size=(64, 48), mode="RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, "teal" if mode == "RGB" else None).save(buf, fmt)
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path):
    app = create_app()
    app.state.images = ImageStore(tmp_path / "work")
    with TestClient(app) as c:
        yield c


def upload(client, *files):
    return client.post("/api/images", files=[("files", f) for f in files])


def test_upload_formats_and_rejects(client):
    r = upload(
        client,
        ("a.jpg", picture("JPEG"), "image/jpeg"),
        ("b.png", picture("PNG", mode="RGBA"), "image/png"),
        ("c.webp", picture("WEBP"), "image/webp"),
        ("d.tif", picture("TIFF"), "image/tiff"),
        ("notes.txt", b"hello", "text/plain"),
        ("fake.jpg", b"not an image", "image/jpeg"),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert [i["mime"] for i in body["images"]] == ["image/jpeg", "image/png", "image/webp", "image/tiff"]
    assert sorted(x["filename"] for x in body["rejected"]) == ["fake.jpg", "notes.txt"]
    first = body["images"][0]
    assert (first["width"], first["height"]) == (64, 48)
    assert first["ai_status"] == "pending" and first["suggestion"] is None
    thumb = client.get(first["thumb_url"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    assert client.get(first["preview_url"]).status_code == 200


def test_phone_photo_mpo_is_a_jpeg():
    """iPhone and camera JPEGs are often MPO (a JPEG with a second picture)."""
    buf = io.BytesIO()
    first, second = Image.new("RGB", (80, 60), "navy"), Image.new("RGB", (40, 30), "gray")
    first.save(buf, "MPO", save_all=True, append_images=[second])
    assert Image.open(io.BytesIO(buf.getvalue())).format == "MPO"
    p = process(buf.getvalue(), "IMG_0042.JPG")
    assert p.mime == "image/jpeg" and (p.width, p.height) == (80, 60)


def test_all_rejected_creates_nothing(client, tmp_path):
    r = upload(client, ("x.gif", picture("GIF", mode="P"), "image/gif"))
    assert r.status_code == 400
    assert list((tmp_path / "work").iterdir()) == []


def test_pixel_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_image_pixels", 1000)
    with pytest.raises(ImageRejected, match="pixels"):
        process(picture(size=(100, 100)), "big.jpg")


def test_byte_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_image_bytes", 10)
    with pytest.raises(ImageRejected, match="limit"):
        process(picture(), "a.jpg")


def test_collection_cap(client, monkeypatch):
    monkeypatch.setattr(settings, "max_images", 2)
    cid = upload(client, ("a.jpg", picture(), "image/jpeg")).json()["id"]
    r = client.post(f"/api/images/{cid}/items", files=[("files", ("b.jpg", picture(), "image/jpeg"))] * 2)
    body = r.json()
    assert len(body["images"]) == 2
    assert len(body["rejected"]) == 1 and "at most 2" in body["rejected"][0]["reason"]


def test_bundle_inheritance_and_cdif(client):
    body = upload(client, ("market.jpg", picture(), "image/jpeg"), ("harbour.png", picture("PNG"), "image/png")).json()
    cid, (img, other) = body["id"], body["images"]
    bundle = {
        "license": LICENCE,
        "keywords": ["fieldwork", "Market"],
        "creators": [{"name": "Ada Lovelace", "kind": "person"}],
        "date_modified": "2026-11-23",
        "description": "not inherited",
    }
    assert client.put(f"/api/images/{cid}/bundle", json=bundle).status_code == 200
    own = {"title": "Village market", "keywords": ["market", "stalls"], "content_url": "https://example.org/m.jpg"}
    out = client.put(f"/api/images/{cid}/items/{img['id']}/info", json=own).json()
    eff = out["effective"]
    assert eff["license"] == LICENCE and eff["creators"][0]["name"] == "Ada Lovelace"
    assert eff["keywords"] == ["market", "stalls", "fieldwork"]  # own first, bundle duplicates dropped
    assert eff["description"] == ""  # a description names one image: never inherited

    doc = client.get(f"/api/images/{cid}/items/{img['id']}/cdif").json()
    assert doc["@type"] == ["schema:Dataset"]
    assert doc["schema:additionalType"] == [{"@id": "schema:ImageObject"}]
    assert doc["schema:name"] == "Village market"
    assert doc["@id"] == f"urn:uuid:{uuid.UUID(img['id'])}"  # canonical, as the QLever graph name
    dist = doc["schema:distribution"][0]
    assert dist["schema:encodingFormat"] == ["image/jpeg"]
    assert dist["schema:contentUrl"] == "https://example.org/m.jpg"
    assert dist["spdx:checksum"]["spdx:checksumValue"] == img["md5"]
    conforms = [c["@id"] for c in doc["schema:subjectOf"]["dcterms:conformsTo"]]
    assert conforms == ["https://w3id.org/cdif/core/1.1", "https://w3id.org/cdif/discovery/1.1"]

    untitled = client.get(f"/api/images/{cid}/items/{other['id']}/cdif").json()
    assert untitled["schema:name"] == "harbour"  # the file name stands in


def test_cdif_passes_shacl(client):
    body = upload(client, ("a.jpg", picture(), "image/jpeg")).json()
    cid, img = body["id"], body["images"][0]
    client.put(f"/api/images/{cid}/bundle", json={"license": LICENCE, "date_modified": "2026-11-23"})
    client.put(f"/api/images/{cid}/items/{img['id']}/info", json={"title": "A teal square", "description": "Test."})
    doc = client.get(f"/api/images/{cid}/items/{img['id']}/cdif").json()
    result = shacl_check(cdif_graph(doc))
    if not result["checked"]:
        pytest.skip(result["reason"])
    assert result["violations"] == [], result["violations"]

    check = client.post(f"/api/images/{cid}/check").json()
    assert check[0]["shacl"]["shapes"] == "CDIF-Discovery-Shapes.ttl"  # the profile an image declares
    assert check[0]["shacl"]["violation_count"] == 0
    complete_only = [m for m in check[0]["shacl"]["warning_messages"] if "CDIFcomplete" in m or "profile" in m]
    assert complete_only == []  # no provenance / variables / other-profile warnings
    assert check[0]["shacl"]["missing_required"] == []


def test_check_reports_missing_required(client):
    body = upload(client, ("a.jpg", picture(), "image/jpeg")).json()
    check = client.post(f"/api/images/{body['id']}/check").json()
    missing = " ".join(check[0]["shacl"]["missing_required"])
    assert "Title" in missing and "Licence" in missing and "Date modified" in missing


def test_zip_has_one_file_per_image(client):
    body = upload(client, ("a.jpg", picture(), "image/jpeg"), ("a.png", picture("PNG"), "image/png")).json()
    r = client.get(f"/api/images/{body['id']}/cdif.zip")
    assert r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        assert names == ["a.cdif.jsonld", "a-2.cdif.jsonld"]
        assert json.loads(zf.read(names[1]))["schema:distribution"][0]["schema:encodingFormat"] == ["image/png"]


def test_delete_image_and_collection(client, tmp_path):
    body = upload(client, ("a.jpg", picture(), "image/jpeg"), ("b.jpg", picture(), "image/jpeg")).json()
    cid, img = body["id"], body["images"][0]
    after = client.delete(f"/api/images/{cid}/items/{img['id']}").json()
    assert [i["filename"] for i in after["images"]] == ["b.jpg"]
    assert client.get(img["thumb_url"]).status_code == 404
    assert client.delete(f"/api/images/{cid}").status_code == 204
    assert client.get(f"/api/images/{cid}").status_code == 404


def test_bad_ids(client):
    assert client.get("/api/images/..%2F..%2Fetc").status_code == 404
    assert client.get("/api/images/abc/items/x/thumb.jpg").status_code == 404


def test_describe_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "n8n_bearer_key", "")
    body = upload(client, ("a.jpg", picture(), "image/jpeg")).json()
    assert body["ai_configured"] is False
    r = client.post(f"/api/images/{body['id']}/items/{body['images'][0]['id']}/describe")
    assert r.status_code == 503


def _fake_n8n(monkeypatch, handler):
    monkeypatch.setattr(settings, "n8n_bearer_key", "Bearer test")
    real = httpx.AsyncClient

    def make(*args, **kwargs):
        return real(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "AsyncClient", make)


def test_describe_is_staged(client, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["multipart"] = b'name="image"' in request.content
        return httpx.Response(200, json={
            "ok": True, "title": "  A teal\nsquare ", "description": "A plain square.",
            "keywords": ["teal", "Teal", "square", ""],
        })

    _fake_n8n(monkeypatch, handler)
    body = upload(client, ("a.jpg", picture(), "image/jpeg")).json()
    cid, iid = body["id"], body["images"][0]["id"]
    out = client.post(f"/api/images/{cid}/items/{iid}/describe").json()
    assert seen == {"auth": "Bearer test", "multipart": True}
    assert out["ai_status"] == "done"
    assert out["suggestion"] == {"title": "A teal square", "description": "A plain square.", "keywords": ["teal", "square"]}
    assert out["info"]["title"] == ""  # nothing is applied until the user accepts it

    # The user accepts the title and keeps the rest pending.
    client.put(f"/api/images/{cid}/items/{iid}/info", json={"title": "A teal square"})
    left = client.put(f"/api/images/{cid}/items/{iid}/suggestion",
                      json={"description": "A plain square.", "keywords": ["teal", "square"]}).json()
    assert left["info"]["title"] == "A teal square" and left["suggestion"]["title"] == ""
    cleared = client.put(f"/api/images/{cid}/items/{iid}/suggestion", json={}).json()
    assert cleared["suggestion"] is None


def test_describe_failure_is_recorded(client, monkeypatch):
    _fake_n8n(monkeypatch, lambda request: httpx.Response(502, json={"ok": False, "error": "model down"}))
    body = upload(client, ("a.jpg", picture(), "image/jpeg")).json()
    out = client.post(f"/api/images/{body['id']}/items/{body['images'][0]['id']}/describe").json()
    assert out["ai_status"] == "failed" and "model down" in out["ai_error"]
    assert out["suggestion"] is None


def test_tabular_endpoints_do_not_see_collections(client):
    body = upload(client, ("a.jpg", picture(), "image/jpeg")).json()
    assert client.get(f"/api/files/{body['id']}").status_code == 404


def photo(taken: str | None) -> bytes:
    """A JPEG with EXIF DateTimeOriginal ``taken`` ("YYYY:MM:DD HH:MM:SS"), or none."""
    im = Image.new("RGB", (32, 24), "teal")
    buf = io.BytesIO()
    if taken is None:
        im.save(buf, "JPEG")
    else:
        exif = Image.Exif()
        exif.get_ifd(0x8769)[36867] = taken
        im.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_import_dates_from_exif_and_file(client):
    r = client.post(
        "/api/images",
        files=[
            ("files", ("taken.jpg", photo("2021:06:15 10:00:00"), "image/jpeg")),
            ("files", ("plain.jpg", photo(None), "image/jpeg")),
            ("files", ("unset.jpg", photo("0000:00:00 00:00:00"), "image/jpeg")),
        ],
        data={"last_modified": ["2023-02-01", "2022-14-40", "2024-05-06"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    dates = [(i["info"]["date_published"], i["info"]["date_modified"]) for i in body["images"]]
    assert dates == [
        ("2021-06-15", "2023-02-01"),  # taken (EXIF), file modified
        ("", ""),  # no EXIF, and an impossible file date is dropped
        ("2024-05-06", "2024-05-06"),  # an unset EXIF date falls back to the file's
    ]
    # Empty bundle dates come from the images: earliest published, latest modified.
    assert (body["bundle"]["date_published"], body["bundle"]["date_modified"]) == ("2021-06-15", "2024-05-06")


def test_import_dates_without_last_modified(client):
    body = upload(client, ("taken.jpg", photo("2020:01:02 03:04:05"), "image/jpeg")).json()
    assert (body["images"][0]["info"]["date_published"], body["images"][0]["info"]["date_modified"]) == ("2020-01-02", "2020-01-02")


def test_import_keeps_bundle_dates(client):
    body = upload(client, ("a.jpg", photo("2020:01:02 03:04:05"), "image/jpeg")).json()
    cid = body["id"]
    client.put(f"/api/images/{cid}/bundle", json={"date_published": "2019-01-01", "date_modified": "2019-02-02"})
    more = client.post(f"/api/images/{cid}/items", files=[("files", ("b.jpg", photo("2025:03:03 00:00:00"), "image/jpeg"))]).json()
    assert (more["bundle"]["date_published"], more["bundle"]["date_modified"]) == ("2019-01-01", "2019-02-02")
    assert more["images"][1]["info"]["date_published"] == "2025-03-03"


def test_image_type_follows_type(client):
    body = upload(client, ("a.jpg", picture(), "image/jpeg")).json()
    doc = client.get(f"/api/images/{body['id']}/items/{body['images'][0]['id']}/cdif").json()
    keys = list(doc)
    assert keys[keys.index("@type") + 1] == "schema:additionalType"
    assert doc["schema:additionalType"] == [{"@id": "schema:ImageObject"}]



# -- QLever: one document per image ----------------------------------------------------


class FakeQlever:
    def __init__(self):
        self.graphs, self.catalog = {}, {}

    async def put_graph(self, name, graph):
        self.graphs[name] = graph

    async def write_catalog_entry(self, entry):
        self.catalog[entry.uuid] = entry

    async def construct_graph(self, name):
        from rdflib import Graph

        return self.graphs.get(name, Graph())

    async def collection_entry(self, doc_uuid):
        e = self.catalog.get(doc_uuid)
        if e is None or e.kind != "image-collection":
            return None
        return {"title": e.title, "bundle": e.bundle, "parts": sorted(e.parts)}


@pytest.fixture()
def fake_qlever(monkeypatch):
    store = FakeQlever()
    for name in ("put_graph", "write_catalog_entry", "construct_graph", "collection_entry"):
        monkeypatch.setattr(qlever, name, getattr(store, name))
    monkeypatch.setattr(settings, "qlever_url", "http://qlever.invalid:7001")
    return store


def test_save_to_qlever_and_open_again(client, fake_qlever):
    body = client.post(
        "/api/images",
        files=[("files", ("harbour.jpg", photo("2021:06:15 10:00:00"), "image/jpeg")),
               ("files", ("b.png", picture("PNG"), "image/png"))],
        data={"last_modified": ["2023-02-01", "2023-02-02"]},
    ).json()
    cid, img = body["id"], body["images"][0]
    client.put(f"/api/images/{cid}/bundle", json={"license": LICENCE, "creators": [{"name": "Ada Lovelace"}]})
    client.put(f"/api/images/{cid}/items/{img['id']}/info",
               json={**img["info"], "title": "The harbour", "description": "Boats at dusk.", "keywords": ["boats"]})

    saved = client.post(f"/api/images/{cid}/qlever").json()["images"]
    assert [r["saved"] for r in saved] == [True, True]
    doc_uuid = str(uuid.UUID(img["id"]))
    assert saved[0]["uuid"] == doc_uuid and saved[0]["graph"] == f"urn:uuid:{doc_uuid}"
    assert saved[0]["shacl"]["shapes"] in (None, "CDIF-Discovery-Shapes.ttl")
    entry = fake_qlever.catalog[doc_uuid]
    assert entry.kind == "image" and entry.title == "The harbour" and entry.source_file == "harbour.jpg"
    assert len(fake_qlever.graphs) == 2  # one graph per image

    opened = client.post(f"/api/images/from-qlever/{doc_uuid}")  # one image of the collection
    assert opened.status_code == 201, opened.text
    coll = opened.json()
    assert coll["id"] != cid and len(coll["images"]) == 1
    back = coll["images"][0]
    assert back["id"] == img["id"] and back["has_picture"] is False and back["ai_status"] == "done"
    assert (back["filename"], back["mime"], back["size"], back["md5"]) == ("harbour.jpg", "image/jpeg", img["size"], img["md5"])
    info = back["info"]
    assert (info["title"], info["description"], info["keywords"]) == ("The harbour", "Boats at dusk.", ["boats"])
    assert info["license"] == LICENCE and info["creators"][0]["name"] == "Ada Lovelace"  # the bundle's, now its own
    assert (info["date_published"], info["date_modified"]) == ("2021-06-15", "2023-02-01")
    assert info["record_id"] == f"urn:uuid:{doc_uuid}"

    # No picture: no preview and no AI description; a re-save replaces the same graph.
    assert client.get(back["preview_url"]).status_code == 404
    assert client.post(f"/api/images/{coll['id']}/items/{back['id']}/describe").status_code in (409, 503)
    again = client.post(f"/api/images/{coll['id']}/qlever").json()["images"]
    assert again[0]["uuid"] == doc_uuid and len(fake_qlever.graphs) == 2


def test_open_image_record_as_data_file_is_refused(client, fake_qlever):
    body = upload(client, ("a.jpg", picture(), "image/jpeg")).json()
    client.post(f"/api/images/{body['id']}/qlever")
    doc_uuid = str(uuid.UUID(body["images"][0]["id"]))
    assert client.post(f"/api/qlever/documents/{doc_uuid}/open").status_code == 409


def test_open_from_qlever_errors(client, fake_qlever):
    assert client.post("/api/images/from-qlever/not-a-uuid").status_code == 400
    assert client.post(f"/api/images/from-qlever/{uuid.uuid4()}").status_code == 404


def test_qlever_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "qlever_url", "")
    body = upload(client, ("a.jpg", picture(), "image/jpeg")).json()
    assert client.post(f"/api/images/{body['id']}/qlever").status_code == 503


def test_catalog_entry_kind():
    from rdflib import DCTERMS, Literal

    entry = qlever.CatalogEntry(uuid=str(uuid.uuid4()), title="t", dataset_iri="urn:x", source_file="a.jpg",
                                triples=1, saved_at="2026-11-25T00:00:00Z", kind="image")
    assert (qlever.entry_iri(entry.uuid), DCTERMS.type, Literal("image")) in qlever._entry_graph(entry)


def test_open_drops_the_file_name_title(client, fake_qlever):
    body = upload(client, ("harbour.jpg", picture(), "image/jpeg")).json()
    client.post(f"/api/images/{body['id']}/qlever")
    doc_uuid = str(uuid.UUID(body["images"][0]["id"]))
    back = client.post(f"/api/images/from-qlever/{doc_uuid}").json()["images"][0]
    assert back["info"]["title"] == ""  # "harbour" was only the stand-in


def test_save_and_open_a_whole_collection(client, fake_qlever):
    body = client.post(
        "/api/images",
        files=[("files", (f"{n}.jpg", photo(None), "image/jpeg")) for n in ("a", "b", "c")],
    ).json()
    cid, imgs = body["id"], body["images"]
    bundle = {"title": "Harbour fieldwork", "license": LICENCE, "creators": [{"name": "Ada Lovelace"}],
              "keywords": ["fieldwork"], "spatial": ["Norway"], "date_modified": "2024-01-01"}
    client.put(f"/api/images/{cid}/bundle", json=bundle)
    # a: inherits everything; b: own licence and creator; c: own keyword and title
    client.put(f"/api/images/{cid}/items/{imgs[1]['id']}/info",
               json={"license": "https://creativecommons.org/publicdomain/zero/1.0/", "creators": [{"name": "Grace Hopper"}]})
    client.put(f"/api/images/{cid}/items/{imgs[2]['id']}/info", json={"title": "The pier", "keywords": ["pier"]})

    saved = client.post(f"/api/images/{cid}/qlever").json()
    coll_uuid = str(uuid.UUID(cid))
    assert saved["uuid"] == coll_uuid and saved["title"] == "Harbour fieldwork"
    entry = fake_qlever.catalog[coll_uuid]
    assert entry.kind == "image-collection" and sorted(entry.parts) == sorted(str(uuid.UUID(i["id"])) for i in imgs)
    assert len(fake_qlever.graphs) == 3  # the collection itself is no CDIF graph

    opened = client.post(f"/api/images/from-qlever/{coll_uuid}")
    assert opened.status_code == 201, opened.text
    coll = opened.json()
    assert coll["id"] == cid  # the same collection: a re-save updates it
    b = coll["bundle"]
    assert (b["title"], b["license"], b["creators"][0]["name"], b["keywords"], b["spatial"]) == (
        "Harbour fieldwork", LICENCE, "Ada Lovelace", ["fieldwork"], ["Norway"])
    own = {i["filename"]: i["info"] for i in coll["images"]}
    assert own["a.jpg"]["license"] == "" and own["a.jpg"]["creators"] == [] and own["a.jpg"]["keywords"] == []
    assert own["a.jpg"]["date_modified"] == "" and own["a.jpg"]["spatial"] == []  # inherited again
    assert own["b.jpg"]["license"].endswith("zero/1.0/") and own["b.jpg"]["creators"][0]["name"] == "Grace Hopper"
    assert own["c.jpg"]["title"] == "The pier" and own["c.jpg"]["keywords"] == ["pier"]
    eff = {i["filename"]: i["effective"] for i in coll["images"]}
    assert eff["a.jpg"]["license"] == LICENCE and eff["c.jpg"]["keywords"] == ["pier", "fieldwork"]

    again = client.post(f"/api/images/{cid}/qlever").json()
    assert again["uuid"] == coll_uuid and len(fake_qlever.graphs) == 3


def test_open_collection_with_a_missing_image(client, fake_qlever):
    body = upload(client, ("a.jpg", picture(), "image/jpeg"), ("b.jpg", picture(), "image/jpeg")).json()
    client.post(f"/api/images/{body['id']}/qlever")
    gone = str(uuid.UUID(body["images"][1]["id"]))
    del fake_qlever.graphs[f"urn:uuid:{gone}"]
    coll = client.post(f"/api/images/from-qlever/{uuid.UUID(body['id'])}").json()
    assert [i["filename"] for i in coll["images"]] == ["a.jpg"]
    assert coll["rejected"][0]["filename"] == gone
