-- Planted against found money per provider × month (evaluation.invoice_level).
select provider, month, planted, findings, planted_minor, findings_minor, gap_minor
from evaluation.invoice_level
