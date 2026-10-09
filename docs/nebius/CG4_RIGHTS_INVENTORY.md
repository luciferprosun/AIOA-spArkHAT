# CG4 rights inventory — no legal attestation

| Scope | Recorded evidence | Status / limitation |
|---|---|---|
| AIOA first-party code | LICENSE, pyproject: MIT / Lukasz Zuchowski | Recorded claim; no independent ownership attestation |
| Memory Patch native import | LICENSE-MEMORY-PATCH.txt + source map | MIT notice/provenance retained |
| NonZero native import | LICENSE-NONZERO.txt + NONZERO_CLOUDOPS provenance | MIT/luciferprosun; imported history retained |
| CPL selective ports | CPL_SOURCE_PORT_MAP.json | MIT attributed source/commit |
| Third-party dependencies | pyproject extras and runtime/requirements.txt | UNKNOWN version-specific licenses/transitive notices; no SBOM/lockfile in current evidence |
| requests direct import | runtime/tools/web_reader.py | Pre-existing undeclared direct dependency; not repaired in this bounded task |
| Packaged knowledge PDFs | pyproject includes knowledge/**/*.pdf; library_manifest.yaml | UNKNOWN creators/redistribution rights: linux_master_library_v1.pdf and RHCSA_Command_Library (1).pdf; lineage hashes are not permission |
| Historical composite PDF | MHLM_MHSR case-study archive/AOIA_Master_Library.pdf | UNKNOWN authorship/rights; preserve without blanket MIT claim |
| NVIDIA Lightning | official NVIDIA model card | OpenMDW-1.1 separate from MIT; hosted provider/model/output terms need human review |
| Other model/provider references | Gemma/NVIDIA/default provider modules | UNKNOWN applicable terms; no bundled weights found in read-only audit |
| Screenshot and future demo media | demo_panel_20261003T131600Z.png | UNKNOWN media rights; future video/music/voice/marks/screens require own inventory |
| AI provenance | GENAI_LOG / GENAI_TRANSPARENCY | Historical limitations disclosed; not blanket originality certification |
| Eligibility/terms/ownership | NVIDIA checklist and maintainer review | HUMAN_ONLY OPEN; no attestation performed |

Dependency declarations: setuptools>=65/wheel; pydantic2.13.4, uuid6 2025.0.1, psycopg[binary]3.3.5; google-genai, Playwright, beautifulsoup4, rich, textual. Validation-only nvidia-nat-atif1.7.0 remains externally pinned. Do not infer package license from root MIT or install additional tools merely to make the list appear complete. Preserve required notices and historical files. Release/publication remains blocked until version-specific license inventory and document/media redistribution scope are human-reviewed.

## Local installed metadata snapshot

Separate external metadata inventory identifies MIT declarations for setuptools68.1.2, wheel0.42.0, pydantic2.13.4/core2.46.4, uuid6 2025.0.1, beautifulsoup4 4.12.3 and rich13.7.1; requests2.31.0 declares Apache2.0; installed psycopg/psycopg-binary3.3.6 declare LGPL-3.0-only. The project optional pin is3.3.5, so this snapshot does not certify a clean pinned install. google-genai, Playwright and Textual were absent from the inspected environment. No auth/direct_url metadata was read. Installed metadata does not establish complete transitive notices, model/provider terms or PDF/media rights. All release/legal unknowns remain open.
