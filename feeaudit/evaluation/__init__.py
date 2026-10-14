"""Evaluation of the engine's findings against the planted truth.

This package is the only code that reads schema `truth`. It writes schema `evaluation`
(replaced on every run) and returns a pass/fail verdict against the thresholds below.

Matching (docs/data-contract.md section 5): a finding matches a truth unit when its
`finding_type` equals the type mapped from the unit's truth id, its party matches, and
- line-level types (D01, D03, D06..D09, D11..D14): its `line_ids` share at least one id
  with the truth row's `line_ids` (for D06/D14 the duplicate/unknown line);
- D04, D15: its `event_id` equals the truth refund event id;
- D02, D05, D10: its `counterparty` equals the provider and its month equals the truth month;
- L01..L04: its `counterparty` equals the client, its month equals the truth month and the
  truth component is among the finding's components. Components are read from a
  `component` column when the client findings table has one; otherwise from `line_ids`,
  each element being either a client invoice line reference `<invoice_id>:<line_no>`
  (mapped through `raw.fernway__client_invoice_lines`) or a component name.

Only rule findings (`method = 'rule'`) are scored. Anomalies (`main.fct_anomalies`, and the
findings with `method = 'anomaly'`) go to `anomaly_report`: every planted anomaly of
`truth.anomalies` with the first day it was detected (same provider and component, card
segments equal or either `all`, on or after the start date), and every detected anomaly that
matches no plant with its explanation. It sets no target and never fails the run.
"""

from feeaudit.evaluation.evaluate import THRESHOLDS, evaluate

__all__ = ["THRESHOLDS", "evaluate"]
