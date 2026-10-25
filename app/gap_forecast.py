"""An open gap cannot gain time from a softer mode or ageing history."""
import math


class GapForecast:
    def __init__(self):
        self.reset()

    def reset(self):
        self.key = None
        self.bound = None
        self.required = None

    def update(self, key, clear, bound, required):
        if not clear:
            # Missing observations do not buy a fresh budget in the same
            # episode. A real busy->clear transition supplies a new cycle key.
            return bound, required
        if key != self.key:
            self.reset()
            self.key = key
        if bound is not None and math.isfinite(float(bound)):
            self.bound = float(bound) if self.bound is None else min(self.bound, float(bound))
        self.required = float(required) if self.required is None else max(self.required, float(required))
        return self.bound, self.required
