# CDIF SHACL shapes (vendored)

`CDIF-Complete-Shapes.ttl` and `CDIF-Discovery-Shapes.ttl` are copied unchanged from the CDIF validation repository
(Apache-2.0), https://github.com/Cross-Domain-Interoperability-Framework/validation,
`ShaclValidation/` at commit ee4edc8901f671fdaaf3d26bd65f96a234a7fa1d.

The Complete profile covers Discovery, DataDescription and DataStructure. A save to
QLever and `POST /api/files/{id}/cdif/check` validate against it; problems are
reported, not enforced. `DDI_CDIF_SHACL_SHAPES` points at another shapes file.

Image records declare only the core and discovery profiles, so the image Check
(`POST /api/images/{id}/check`) validates against `CDIF-Discovery-Shapes.ttl`; the
override above does not apply to it.

To update: copy the files again from the new commit and change the commit above.
