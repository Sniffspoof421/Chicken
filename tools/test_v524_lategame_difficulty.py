from app.risk import RiskEngine
r=object.__new__(RiskEngine)
r.live_speed_easy_px_s=120.0
r.live_speed_hard_px_s=360.0
r.live_gap_min_support=8
r.live_gap_easy_seconds=1.1
r.live_gap_hard_seconds=.42
ctx={'raw_p95':33.0,'event_p95':350.0,'confirmed_events':4,'unique_raw_tracks':2}
motion={'support':50,'p25':1.44,'busy_fraction':.10}
d,s,dens=RiskEngine._live_difficulty(r,ctx,motion,fallback=.10)
assert s > .75,(d,s,dens)
assert d > .20,(d,s,dens)
# Easy recent traffic must stay easy even if fallback prior is somewhat hard.
ctx2={'raw_p95':80.0,'event_p95':90.0,'confirmed_events':4,'unique_raw_tracks':2}
d2,s2,dens2=RiskEngine._live_difficulty(r,ctx2,motion,fallback=.35)
assert s2 < .05,(d2,s2,dens2)
assert d2 < .20,(d2,s2,dens2)
print('PASS v524 recent-event late-game difficulty fallback')
