"""Report causal-outcome coverage without counting manual resets as GREEN failures."""
import argparse,json,collections
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('audit',type=Path)
a=p.parse_args()
rows=[json.loads(s) for s in a.audit.read_text().splitlines() if s.strip()]
# A reset with no observed action is unresolved proximity evidence, not an attempt.
attempts=[r for r in rows if r.get('kind','green_outcome')=='green_outcome'
          and r.get('action_start_ts') is not None
          and r.get('unknown_reason')!='reset_without_observed_action']
c=collections.Counter(r.get('outcome') for r in attempts)
n=len(attempts);resolved=c['success']+c['failure']
print(json.dumps(dict(attributed_attempt_records=n,success=c['success'],failure=c['failure'],
    unresolved=n-resolved,unknown=c['unknown'],chained_unvalidated=c['chained_unvalidated'],
    logged_success_share_of_attempts=None if not n else c['success']/n,
    resolved_record_success_rate=None if not resolved else c['success']/resolved,
    note='Record coverage only; uncertain action timing and inferred scroll outcomes prevent a physical accuracy estimate.'),indent=2))
