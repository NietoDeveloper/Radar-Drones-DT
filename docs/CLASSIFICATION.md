# Micro-Doppler classification

## 1. Physics in one page

A target moving radially at `v` shifts the carrier by `f_d = 2v/λ` (the **body line**). Moving parts
phase-modulate the return around it:

* **Multirotor:** 4–8 rotors × 2–3 blades spinning at 3 000–9 000 rpm. Blade tips move at tens of m/s
  → micro-Doppler spread of several kHz at X band, a **stationary** comb-like spectrum (rotor speed is
  nearly constant over a dwell).
* **Bird:** wings flap at ~3–14 Hz with sub-metre amplitude → a spread of a few hundred Hz that is
  **strongly time-varying** (flap cycle, glide phases).
* **Clutter** (rain, foliage): Gaussian-shaped, noise-like spectrum without a ri
`classification/microdoppler.py` synthesises all three rom these models (random rotor count, blade
count, rpm, radius, projection, flap rate, amplitude, glide envelope, SNR, radial velocity, PRF) so the
pipeline can be trained and tested without hardware and so every assumpt
## 2. Features (`md_features`)
ide for rotors |
| `occupied_fraction` | Fraction of bins within 2
## 3. Model

Standardised features + squared terms → multinomial logistic regression (numpy at inference, scipy L-BFGS
for training). Packaged weights: `classification/models/microdoppler_v1.npz`; the file records the feature
names and the loader refuses a mismatch.

Retrain: `sdt-radar train-classifier` (deterministic seed; writes the packaged file).

**Per-track evidence.** Each dwell yields class probabilities `p`. The track keeps
`logp ← 0.92·logp + log p` (forgetting 0.92) and reports the posterior; it is labelled only when the
maximum reaches `decision_threshold` (0.7), otherwise `unknown`. A few dwells turn a ~91 % per-dwell
classifier into a near-certain track-level label (tested: 6 dwells at 10 dB SNR → bird with > 0.9).

## 4. Measured performance (synthetic, held-out seeds)

| Metric | Value |
|---|---|
| Per-dwell accuracy, all SNR 4–25 dB | **91 %** |
| Drone recall / bird recall / clutter recall | 97 % / 94 % / 81 % |
| Clutter mistaken for bird | the main error (≈ 10–16 %) |
| Drone ↔ bird confusion | < 5 % per dwell in tests (the confusion that matters) |
| Track level, perimeter scenario (8 seeds) | 100 % class accuracy on classified matched tracks, 0 drone↔bird confusions |
| Accuracy by SNR band (4–10 / 10–16 / 16–25 dB) | ≈ 90 % / 95 % / 96 % |

## 5. What this does NOT prove

These numbers come from signatures made by the same generator that built the training set. Real
radars add range-cell leakage, antenna patterns, multipath, receiver non-linearities, real animal and
drone variety (large birds, flocks, small drones with folding props, helicopters, fixed-wing drones with a
single pusher propeller). **Treat the classifier as a working, testable baseline and a plug-in point, not
as a validated 97 % system.** The reported > 97 % in the literature is for deep models trained on real
recordings.

## 6. Making it real

1. Record labelled dwells at your site (drone flights with known models; bird-rich periods; rain/clutter).
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
