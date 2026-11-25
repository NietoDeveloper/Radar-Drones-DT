"""Sensor models: a radar (Swerling-I detection, range-dependent noise, clutter, micro-Doppler dwell) and
generic position-fix sources (Remote ID, RF geolocation, EO/IR triangulation).

Detection model: the radar is specified by ``r90_m`` — the range at which a 0.01 m² (-20 dBsm) target
is detected with Pd = 0.9 at the configured Pfa. SNR then scales as ``-40 log10(R)`` and with RCS; Pd
follows the Swerling-I relation ``Pd = Pfa ** (1 / (1 + SNR))``. This is a planning-grade model, not a
waveform-level simulation.
""")) > self.max_range_m or rng.random() > self.pd:
                continue