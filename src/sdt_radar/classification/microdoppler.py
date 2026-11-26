"""Micro-Doppler signal synthesis and feature extraction.

A target's radial motion shifts the carrier by ``fd = 2 v / lambda`` (the "body line"). Moving parts add
phase modulation around it: rotor blades of a multirotor (fast, stationary, comb-like harmonics spread
over kHz) versus flapping wings of a bird (slow, strongly time-varying, spread of a few hundred Hz).
Both are synthesised here from first principles so the classifier can be trained and tested without
hardware, and so every radar-band / PRF assumption is explicit.

Everything works on *slow-time complex samples* at the radar PRF (a short dwell on one target).
"""

from __future__ import annotations
        r_wing = amp * envelope * np.sin(phase + (0.0 if side < 0 else rng.uniform(-0.3, 0.3)))
        s = s + 0.5 * np.exp(1j * (2 * np.pi * fd * t + 4 * np.pi * r_wing / lam))
    bob = 0.02 * np.sin(phase * 0.5)
    s = s * np.exp(1j * 4 * np.pi * bob / lam)
    s = s / np.sqrt(np.mean(np.abs(s) ** 2))
    return s + _noise(rng, n, 10 ** (-snr_db / 10.0))


def synth_clutter(
    rng: np.random.Generator,
    n: int,
    prf_hz: float,
    fc_hz: float = 10e9,
    radial_v_mps: float = 0.0,
    snr_db: float = 12.0,
) -> Complex:
    """Rain / foliage / ground clutter: Gaussian-spectrum coloured noise, no rigid body line."""
    width_hz = float(rng.uniform(15.0, 300.0))
    white = _noise(rng, n, 1.0)
    spec = np.fft.fft(white)
    f = np.fft.fftfreq(n, d=1.0 / prf_hz)
    shape = np.exp(-0.5 * (f / width_hz) ** 2)
    s = np.fft.ifft(spec * shape)
    s = s / np.sqrt(np.mean(np.abs(s) ** 2))
    t = np.arange(n) / prf_hz
    s = s * np.exp(1j * 2 * np.pi * (2 * radial_v_mps / (C0 / fc_hz)) * t)
    return s + _noise(rng, n, 10 ** (-snr_db / 10.0))


def md_features(iq: NDArray[np.complex64] | Complex, prf_hz: float, nperseg: int = 128) -> NDArray[np.float64]:
    """Fixed-length, shift-invariant feature vector (see ``FEATURE_NAMES``)."""
    x = np.asarray(iq, dtype=np.complex128)
    x = x - np.mean(x) * 0.0  # keep the DC/body line: it is the reference, not noise
    if x.size < nperseg * 2:
        raise ValueError(f"need at least {nperseg * 2} samples, got {x.size}")
    _, _, z = stft(x, fs=prf_hz, window="hann", nperseg=nperseg, noverlap=nperseg * 3 // 4,
                   return_onesided=False, boundary=None, padded=False)
    pw = np.fft.fftshift(np.abs(z) ** 2, axes=0) + 1e-18  # (F, T)
    mean_spec = pw.mean(axis=1)
    k0 = int(np.argmax(mean_spec))
    shift = nperseg // 2 - k0
    pw = np.roll(pw, shift, axis=0)  # put the body line at the centre bin
    mean_spec = pw.mean(axis=1)
    bin_hz = prf_hz / nperseg
    f_khz = (np.arange(nperseg) - nperseg // 2) * bin_hz / 1000.0

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
