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
    centroid = float((f_khz * sig).sum() / tot)
    rms_bw = float(np.sqrt(((f_khz - centroid) ** 2 * sig).sum() / tot))

    peak = float(np.max(mean_spec))
    occupied = float(np.mean(mean_spec > peak * 10 ** (-2.0)))  # bins within 20 dB of the peak
    flat = float(np.exp(np.mean(np.log(mean_spec))) / np.mean(mean_spec))

    logs = np.log(pw)
    logm = np.log(mean_spec)
    a = logs - logs.mean(axis=0, keepdims=True)
    b = (logm - logm.mean())[:, None]
    corr = (a * b).sum(axis=0) / (np.linalg.norm(a, axis=0) * np.linalg.norm(b) + 1e-12)
    stationarity = float(corr.mean())

    lm = logm - logm.mean()
    ac = np.correlate(lm, lm, mode="full")[nperseg - 1 :]
    ac = ac / (ac[0] + 1e-12)
    comb = float(ac[3 : nperseg // 3].max())

    p2f = float(10 * np.log10(peak / (floor + 1e-18)))
    cents = (f_khz[:, None] * pw).sum(axis=0) / pw.sum(axis=0)
    jitter = float(cents.std())

    return np.array([rms_bw, occupied, flat, stationarity, comb, p2f, jitter], dtype=float)
