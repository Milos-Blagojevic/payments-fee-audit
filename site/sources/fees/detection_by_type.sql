-- Precision and recall per planted discrepancy type (evaluation.detection_by_type).
select
    truth_id,
    finding_type,
    planted,
    found,
    findings,
    true_positives,
    precision,
    recall,
    planted_minor,
    found_minor,
    money_recall
from evaluation.detection_by_type
