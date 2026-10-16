"""Structure of the generated document: types, counts, ids and the physical layer.

The code list branch is the canonical DDI-CDI ``CodeList`` / ``Code`` / ``Category`` /
``Notation``; the original app expressed value labels as a SKOS concept scheme instead.
"""

import json
from collections import Counter

from ddicdi.cdi.jsonld import CONTEXT, generate_complete_json_ld
from ddicdi.importers import import_file
from ddicdi.roles import parse_roles
from tests.conftest import original_file


def _all(doc):
    return doc["DDICDIModels"] + doc.get("@included", [])


def test_ess11_structure(ess11):
    doc = json.loads(generate_complete_json_ld(ess11, spssfile="ESS11-subset.sav", max_rows=5))
    assert doc["@context"] == CONTEXT
    ids = [x["@id"] for x in doc["DDICDIModels"]]
    # the physical layer first, in the order the original app wrote it
    assert ids[:3] == ["#structuredDataSet", "#segment", "#segmentPosition"]
    assert ids[3] == "#locatorMapping-name" and ids[16] == "#physicalMappingPosition-name"
    assert ids.index("#logicalRecord") < ids.index("#wideDataSet")
    assert len(ids) == len(set(ids))

    pds = next(x for x in doc["DDICDIModels"] if x["@id"] == "#structuredDataSet")
    assert pds["@type"] == "StructuredDataSet"  # a SAV is a binary file, not tabular text
    assert pds["name"] == {"@type": "ObjectName", "name": "ESS11-subset.sav"}
    assert pds["recordCount"] == 2420
    assert pds["uses_LogicalRecord"] == "#logicalRecord" and pds["correspondsTo_DataSet"] == "#wideDataSet"
    assert pds["has_Segment"] == ["#segment"] and pds["has_SegmentPosition"] == ["#segmentPosition"]
    assert len(pds["has_PhysicalMapping"]) == len(pds["has_PhysicalMappingPosition"]) == 13
    assert "has_InstanceVariable" not in pds  # the mappings' ``formats`` and the LogicalRecord cover it
    assert "isDelimited" not in pds

    seg = next(x for x in doc["DDICDIModels"] if x["@id"] == "#segment")
    assert seg["physicalFileName"] == "ESS11-subset.sav" and seg["mapsTo"] == "#logicalRecord"
    assert len(seg["has_DataPoint"]) == len(seg["has_DataPointPosition"]) == 13 * 5

    pm = next(x for x in doc["DDICDIModels"] if x["@id"] == "#locatorMapping-ppltrst")
    assert pm["@type"] == "LocatorMapping" and pm["formats"] == "#instanceVariable-ppltrst"
    assert pm["locator"] == "ppltrst"
    assert pm["format"]["entryValue"] == str(ess11.meta.var("ppltrst").format)
    assert pm["maximumLength"] == ess11.meta.var("ppltrst").width and "nullSequence" not in pm
    iv = next(x for x in doc["DDICDIModels"] if x["@id"] == "#instanceVariable-ppltrst")
    assert iv["physicalDataType"]["entryValue"] == ess11.meta.var("ppltrst").storage_type  # not the format

    wds = next(x for x in doc["DDICDIModels"] if x["@id"] == "#wideDataSet")
    assert wds["has_InstanceVariable"] == [f"#instanceVariable-{v}" for v in ess11.meta.column_names]
    assert wds["recordCount"] == 2420

    iv = next(x for x in doc["DDICDIModels"] if x["@id"] == "#instanceVariable-ppltrst")
    assert not {"has_PhysicalSegmentLayout", "has_ValueMapping", "variableFunction", "isDescribedBy"} & iv.keys()


def test_counts_for_five_rows(ess11):
    doc = json.loads(generate_complete_json_ld(ess11, max_rows=5))
    c = Counter(x["@type"] for x in _all(doc))
    assert c["DataPoint"] == c["DataPointPosition"] == c["InstanceValue"] == 13 * 5
    assert c["LocatorMapping"] == c["PhysicalMappingPosition"] == c["InstanceVariable"] == 13
    assert c["StructuredDataSet"] == c["Segment"] == c["SegmentPosition"] == c["LogicalRecord"] == 1
    assert "LogicalRecordRepository" not in c  # optional in 1.1; the physical data set uses the record directly
    assert c["SentinelValueDomain"] == 2
    # 67 labelled codes over 5 code lists (3 substantive, 2 sentinel), four nodes each
    assert c["CodeList"] == 5
    assert c["Code"] == c["CodePosition"] == c["Category"] == c["Notation"] == 67
    pds = next(x for x in doc["DDICDIModels"] if x["@id"] == "#structuredDataSet")
    assert pds["recordCount"] == 2420  # full file, not the 5 emitted rows


def test_metadata_only_mode(ess11):
    doc = json.loads(generate_complete_json_ld(ess11, max_rows=0))
    types = Counter(x["@type"] for x in _all(doc))
    for t in ("DataPoint", "DataPointPosition", "InstanceValue"):
        assert t not in types
    seg = next(x for x in doc["DDICDIModels"] if x["@type"] == "Segment")
    assert "has_DataPoint" not in seg and "has_DataPointPosition" not in seg
    # the mappings describe the columns, so they stay
    assert types["LocatorMapping"] == types["PhysicalMappingPosition"] == 13


def test_process_all_rows(ess11):
    doc = json.loads(generate_complete_json_ld(ess11, process_all_rows=True, chunk_size=1000))
    c = Counter(x["@type"] for x in _all(doc))
    assert c["InstanceValue"] == c["DataPoint"] == 13 * 2420
    ids = [x["@id"] for x in doc["DDICDIModels"] if x["@type"] == "InstanceValue"]
    # chunk-major, then variable-major, then row (same as the original chunked loop)
    assert ids[0] == "#instanceValue-0-name" and ids[1] == "#instanceValue-1-name"
    assert ids[1000] == "#instanceValue-0-essround"
    assert ids[-1] == "#instanceValue-2419-psu"


def test_roles_primary_key_and_positions(ess11):
    ess11.meta.roles = parse_roles(ess11.meta, {"idno": "identifier", "cntry": "measure,attribute"})
    doc = json.loads(generate_complete_json_ld(ess11, max_rows=1))
    by_type = {}
    for x in doc["DDICDIModels"]:
        by_type.setdefault(x["@type"], []).append(x)
    assert by_type["PrimaryKey"][0]["isComposedOf"] == ["#primaryKeyComponent-idno"]
    assert [x["@id"] for x in by_type["IdentifierComponent"]] == ["#identifierComponent-idno"]
    assert [x["@id"] for x in by_type["AttributeComponent"]] == ["#attributeComponent-cntry"]
    assert "#measureComponent-idno" not in [x["@id"] for x in by_type["MeasureComponent"]]
    assert "#measureComponent-cntry" in [x["@id"] for x in by_type["MeasureComponent"]]
    positions = by_type["ComponentPosition"]
    assert len(positions) == 12 + 2  # 12 measures (idno is identifier only) + cntry attribute + idno identifier
    assert [p["value"] for p in positions] == list(range(14))
    wds = by_type["WideDataStructure"][0]
    assert wds["has_PrimaryKey"] == "#primaryKey"
    assert len(wds["has_DataStructureComponent"]) == 14
    ess11.meta.roles = parse_roles(ess11.meta, {})


def test_sentinel_domain_used_for_declared_missing_values(sentinel_qsv, work_dir):
    """NES1948 row 591 has v480005 = 9 (declared missing 9..inf). qsv keeps the code in
    the cell, so the instance value is 9 and takes its value from the sentinel domain."""
    ds = import_file(original_file("NES1948.sav"), work_dir, sentinel_qsv)
    assert ds.meta.sentinels_in_data
    doc = json.loads(generate_complete_json_ld(ds, process_all_rows=True, chunk_size=5000))
    iv = next(x for x in doc["DDICDIModels"] if x["@id"] == "#instanceValue-591-v480005")
    assert iv["content"]["content"] == "9"
    assert iv["hasValueFrom_ValueDomain"] == "#sentinelValueDomain-v480005"
    codes = next(x for x in doc["DDICDIModels"] if x["@id"] == "#sentinelCodeList-v480005")
    assert codes["has_Code"] == ["#code-v480005-0", "#code-v480005-9"]
    desc = next(x for x in doc["DDICDIModels"] if x["@id"] == "#sentinelValueAndConceptDescription-v480005")
    assert "maximumValueExclusive" not in desc  # open ended range
    assert desc["minimumValueExclusive"] == "0"


def test_csv_upload_is_a_tabular_text_dataset(qsv, work_dir):
    ds = import_file(original_file("sample_data.csv"), work_dir, qsv)
    doc = json.loads(generate_complete_json_ld(ds, max_rows=2))
    pds = next(x for x in doc["DDICDIModels"] if x["@id"] == "#tabularTextDataSet")
    assert pds["@type"] == "TabularTextDataSet"
    assert pds["isDelimited"] is True and pds["isFixedWidth"] is False and pds["delimiter"] == ";"
    assert pds["hasHeader"] is True and pds["headerRowCount"] == 1
    pm = next(x for x in doc["DDICDIModels"] if x["@id"] == "#textMapping-age")
    assert pm["@type"] == "TextMapping" and pm["formats"] == "#instanceVariable-age"
    assert "locator" not in pm
    assert pm["format"]["entryValue"] == "F2.0" and pm["maximumLength"] == 2 and pm["decimalPositions"] == 0
    assert pm["defaultDecimalSeparator"] == "." and pm["nullSequence"] == ""
    name = next(x for x in doc["DDICDIModels"] if x["@id"] == "#textMapping-name")
    assert name["format"]["entryValue"] == "A15" and name["maximumLength"] == 15
    assert "decimalPositions" not in name and "defaultDecimalSeparator" not in name
    svd = next(x for x in doc["DDICDIModels"] if x["@id"] == "#substantiveValueDomain-age")
    assert svd["recommendedDataType"]["entryValue"].endswith("#decimal")
