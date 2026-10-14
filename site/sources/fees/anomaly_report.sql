-- Planted anomaly patterns and detections that match no plant (evaluation.anomaly_report).
select
    category,
    anomaly_id,
    provider,
    component,
    card_segment,
    line_type,
    rate_bps,
    start_date,
    planted_lines,
    planted_minor,
    detected,
    first_detected_day,
    days_to_detect,
    detected_anomaly_id,
    anomaly_type,
    detections,
    coalesce(explained_by, 'unexplained') as explained_by,
    is_finding,
    explanation
from evaluation.anomaly_report
