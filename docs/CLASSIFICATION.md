# Micro-Doppler classification

## 1. Physics in one page

A target moving radially at `v` shifts the carrier by `f_d = 2v/λ` (the **body line**). Moving parts
phase-modulate the return around it:

* **Multirotor:** 4–8 rotors × 2–3 blades spinning at 3 000–9 000 rpm. Blade tips move at tens of m/s
  → micro-Doppler spread of several kHz at X band, a **stationary** comb-like spectrum (rotor speed is
  nearly constant over a dwell).
* **Bird:** wings flap at ~3–14 Hz with sub-metre amplitude → a spread of a few hundred Hz that is
  **strongly time-varying** (flap cycle, glide phases).
* **Clutter** (rain, foliage): Gaussian-shaped, noi these models (random rotor count, b
count, rpm, radius, projection, flap rate, amplitu`. The track keeps
`logp ← 0.92·logp + log p` (forgetting 0.92rts the posteriong props, helicopters, fixed-wing drones with a
single pusher propeller). **Treat the classifier as a working, testable baseline and a plug-in point, notwith known models; bird-rich periods; rain/clutter).
2. Export them in the same shape (`complex64` slow-time samples + PRF) and extend `make_dataset` or
   write your own loader.
3. Retrain; evaluate on held-out *sites/days*, not only held-out samples.
4. Optional: replace the model with a CNN on spectrograms or range-Doppler maps. Implement
   `predict_proba(iq, prf_hz) -> np.ndarray[3]` in the order `[drone, bird, clutter]` and pass it:
   `Pipeline(settings, classifier=MyCnn())`. No other code changes.
5. Keep per-band models: the packaged one assumes X band (λ = 3 cm).

## 6.1 Limits to respect

Minimum dwell is 256 samples (shorter payloads are counted as `classifier_rejected`). Feature units are
Hz-based, so training should cover the PRFs you will use (10 240 and 16 384 Hz are covered).
