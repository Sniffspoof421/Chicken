"""Slow-following profiles in the same forward-speed frame as live geometry."""
from collections import defaultdict
import math
import numpy as np


def motion_class(event):
    forward=event.get('forward_class')
    return str(forward if forward in ('S','M','F') else event.get('class','M'))


def build_slow_profile(events,lane,segment,min_gap,max_gap,min_support,now,recent_seconds=180.,directional=True):
    lane=int(lane)
    classify=motion_class if directional else lambda event:str(event.get('class','M'))
    pools=defaultdict(list)
    mismatch=0
    for li,hist in events.items():
        segments=defaultdict(list)
        for event in hist:
            if event.get('token')=='<RESET>':
                continue
            segments[int(event.get('segment',0))].append(event)
            if event.get('forward_class') in ('S','M','F') and event.get('forward_class')!=event.get('class'):
                mismatch+=1
        for seg,rows in segments.items():
            rows=sorted(rows,key=lambda e:float(e.get('ts',0.)))
            for a,b in zip(rows,rows[1:]):
                if classify(a)!='S':
                    continue
                try:
                    gap=float(b.get('gap'))
                except (ValueError,TypeError):
                    continue
                if not math.isfinite(gap) or not min_gap<=gap<=max_gap:
                    continue
                pair=(gap,classify(b))
                pools['global'].append(pair)
                if int(li)==lane:
                    pools['lane'].append(pair)
                # A recent pair must have BOTH events in the current segment
                # and time window. No reset or stale-history bridge is learned.
                if directional and seg==int(segment) and float(now)-recent_seconds<=float(a.get('ts',0.))<=float(b.get('ts',0.))<=float(now):
                    pools['recent-global'].append(pair)
                    if int(li)==lane:
                        pools['recent-lane'].append(pair)
    if len(pools['recent-lane'])>=min_support:
        source='recent-lane'
    elif len(pools['recent-global'])>=2*min_support:
        source='recent-global'
    elif len(pools['lane'])>=min_support:
        source='lane'
    else:
        source='global'
    pairs=pools[source]
    support=len(pairs)
    out=dict(ready=bool(support),source=source if support else 'none',support=support,
             lane_support=len(pools['lane']),p25_gap=None,median_gap=None,
             p_fast_after_slow=1.,p_slow_or_medium_after_slow=0.,confidence=0.,
             recent_lane_support=len(pools['recent-lane']),
             recent_global_support=len(pools['recent-global']),
             historical_support=len(pools['global']),class_mismatches=mismatch)
    if not support:
        return out
    gaps=np.asarray([g for g,c in pairs],dtype=float)
    pfast=sum(c=='F' for g,c in pairs)/support
    p25=float(np.percentile(gaps,25))
    # Same existing confidence formula and support scale.
    conf=float(np.clip(.42*min(1.,support/12.)+.36*(1.-pfast)
                       +.22*np.clip((p25-.80)/.90,0.,1.),0.,1.))
    out.update(p25_gap=p25,median_gap=float(np.median(gaps)),
               p_fast_after_slow=pfast,
               p_slow_or_medium_after_slow=sum(c in ('S','M') for g,c in pairs)/support,
               confidence=conf)
    return out
