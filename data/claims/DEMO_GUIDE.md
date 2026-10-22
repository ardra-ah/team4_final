# Demo claims guide

All claims are synthetic. Upload each PDF in the web app and compare the result with the table.

| File | What it tests | Expected route | Expected decision |
|---|---|---|---|
| demo01_complete_approve.pdf | Complete claim, routine visit. Should be approved. | approval | APPROVED |
| demo02_missing_diagnosis.pdf | Diagnosis code missing. Should ask for documents. | clarification | PENDING_DOCUMENTS |
| demo03_missing_diagnosis_CORRECTED.pdf | Corrected version of demo02 with the diagnosis added. Use it to test resubmission. | approval | APPROVED |
| demo04_missing_policy_number.pdf | Policy number missing. Should ask for documents. | clarification | PENDING_DOCUMENTS |
| demo05_missing_service_date.pdf | Service date missing. Should ask for documents. | clarification | PENDING_DOCUMENTS |
| demo06_missing_amounts.pdf | Both amounts missing. Should ask for documents and list both fields. | clarification | PENDING_DOCUMENTS |
| demo07_missing_procedure_code.pdf | Procedure code missing. Should ask for documents. | clarification | PENDING_DOCUMENTS |
| demo08_several_missing_fields.pdf | Three fields missing at once. Should list all three. | clarification | PENDING_DOCUMENTS |
| demo09_blank_diagnosis_line.pdf | Diagnosis line present but left blank. Should count as missing. | clarification | PENDING_DOCUMENTS |
| demo10_policy_waiting_period.pdf | Service inside the waiting period and an excluded procedure. Should be rejected after review. | rejection_review | REJECTED |
| demo11_duplicate_of_history.pdf | Matches the seeded history claim CLM-2026-HIST-001. Should be escalated for investigation. | investigation | ESCALATED |
| demo12_high_amount.pdf | Billed amount about eleven times the typical rate. Should be escalated. | investigation | ESCALATED |
| demo13_scanned_missing_diagnosis.pdf | Scanned image with diagnosis missing. Tests OCR together with missing fields. | clarification | PENDING_DOCUMENTS |
| demo14_scanned_complete.pdf | Scanned image, complete claim. Tests OCR on a clean claim. | approval | APPROVED |

Resubmission test: upload demo02 first, reject it with Request documents, then upload demo03 using the resubmit section. The new run should be linked to the original.
