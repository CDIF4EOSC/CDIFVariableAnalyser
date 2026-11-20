# CDIF SHACL shapes (vendored)

`CDIF-Complete-Shapes.ttl` is copied unchanged from the CDIF validation repository
(Apache-2.0), https://github.com/Cross-Domain-Interoperability-Framework/validation,
`ShaclValidation/CDIF-Complete-Shapes.ttl` at commit ee4edc8901f671fdaaf3d26bd65f96a234a7fa1d.

The Complete profile covers Discovery, DataDescription and DataStructure. A save to
QLever and `POST /api/files/{id}/cdif/check` validate against it; problems are
reported, not enforced. `DDI_CDIF_SHACL_SHAPES` points at another shapes file.

To update: copy the file again from the new commit and change the commit above.
