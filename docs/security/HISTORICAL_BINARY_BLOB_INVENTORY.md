# Historical binary blob inventory

Prepared at local HEAD: 88f659a3197a3a49ac94881eff173e0cae0c58bc.

The prior history scan intentionally did not text-scan binary objects. This inventory closes the path/type ambiguity only; it does not claim secret-free embedded content or redistribution rights.

| Git object | Path | Bytes | Classification |
|---|---|---:|---|
| 517b8e17d5a0 | archive/forensic_exports/reports_forensic_export/architecture_and_runtime.pdf | 305586 | KNOWN_BINARY_DOCUMENT_REVIEW_REQUIRED |
| 6efdedda1eeb | archive/forensic_exports/reports_forensic_export/forensic_full_snapshot.pdf | 115341 | KNOWN_BINARY_DOCUMENT_REVIEW_REQUIRED |
| fa28470545d7 | archive/forensic_exports/reports_forensic_export/memory_and_provenance.pdf | 264150 | KNOWN_BINARY_DOCUMENT_REVIEW_REQUIRED |
| 05c293ed637a | archive/forensic_exports/reports_forensic_export/retrieval_and_knowledge_layer.pdf | 718748 | KNOWN_BINARY_DOCUMENT_REVIEW_REQUIRED |
| a2d92651d66d | docs/reports/AOIA_RESTART_PRODUCTION_REPORT.pdf | 134337 | KNOWN_BINARY_DOCUMENT_REVIEW_REQUIRED |
| 9dea6f16ea42 | evidence/personal_ai_vertical_slice/demo_panel_20261003T131600Z.png | 174955 | KNOWN_IMAGE_ARTIFACT_REVIEW_REQUIRED |
| 84c81e9fbd45 | runtime/knowledge/source/linux_master_library_v1.pdf | 1144661 | KNOWN_BINARY_DOCUMENT_REVIEW_REQUIRED |
| 77198d71937b | runtime/nonzero_cloudops/baseline/docs/assets/judge-ux-desktop-denied.png | 475776 | KNOWN_IMAGE_ARTIFACT_REVIEW_REQUIRED |
| b1976e555f95 | runtime/nonzero_cloudops/baseline/docs/assets/judge-ux-desktop-success.png | 532303 | KNOWN_IMAGE_ARTIFACT_REVIEW_REQUIRED |
| e2cdd0b3e6be | runtime/nonzero_cloudops/baseline/docs/assets/judge-ux-mobile-success.png | 318344 | KNOWN_IMAGE_ARTIFACT_REVIEW_REQUIRED |

Result: all ten previously counted binary objects are now path/type identified. External security/IP review remains required before public release.
