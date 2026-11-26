"""Micro-Doppler signal synthesis and feature extraction.

A target's radial motion shifts the carrier by ``fd = 2 v / lambda`` (the "body line"). Moving parts add
phase modulation around it: rotor blades of a multirotor (fast, stationary, comb-like harmonics spread
over kHz) versus flapping wings of a bird (slow, strongly time-varying, spread of a few hundred Hz).
Both are synthesised here from first principles so the classifier can be trained and tested without
hardware, and so every radar-band / PRF assumption is explicit.

) -> Complex:
    """Rain / foliage / ground clutter: Gaussian-spectrum coloured noise, no rigid body line."""
    width_hz = float(rng.uniform(15.s
    floor = float(np.median(mean_spec))
    sig = np.clip(mean_spec - floor, 0.0, None)
    tot = float(sig.sum()) + 1e-18
    corr = (a * b).sum(axis=0) / (np.linalg.norm(a, axis=0) * np.linalg.norm(b) + 1e-12)
    stationarity = float(corr.mean())

    lm = logm - logm.mean