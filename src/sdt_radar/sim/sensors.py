"""Sensor models: a radar (Swerling-I detection, range-dependent noise, clutter, micro-Doppler dwell) and
generic position-fix sources (Remote ID, RF geolocation, EO/IR triangulation).

Detection model: the radar is specified by ``r90_m`` — the range at which a 0.01 m² (-20 dBsm) target
is detected with Pd = 0.9 at the configured Pfa. SNR then scales as ``-40 log10(R)`` and with RCS; Pd
follows the Swerling-I relation ``Pd = Pfa ** (1 / (1 + SNR))``. This is a planning-grade model, not a
waveform-level simulation.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..classification.microdoppler import synth_bird, synth_clutter, synth_multirotor
from ..geo import LocalFrame, enu_to_polar
from ..models import Detection, SensorConfig, encode_iq
from .targets import Target

RCS_REF_DBSM = -20.0  # 0.01 m²


@dataclass
class RadarModel:
    sensor: SensorConfig
    r90_m: float
    scan_period_s: float
    rotating: bool = True
    pfa: float = 1e-6
    fa_per_scan: float = 1.0
    min_range_m: float = 60.0
    max_elev_deg: float = 60.0
    md_prf_hz: float = 10_240.0
    md_samples: int = 1024
    md_probability: float = 0.5
    fc_hz: float = 10e9

    @property
    def max_range_m(self) -> float:
        return self.sensor.max_range_m or self.r90_m * 1.6

    @property
    def snr90_lin(self) -> float:
        return math.log(self.pfa) / math.log(0.9) - 1.0

    def scan(self, t_rel: float, t0_epoch: float, targets: list[Target], frame: LocalFrame,
             rng: np.random.Generator) -> list[Detection]:
        s = self.sensor
        s_enu = frame.to_enu(s.lat, s.lon, s.alt_m)
        out: list[Detection] = []
        snr90_db = 10 * math.log10(self.snr90_lin)
        for tg in targets:
            if not tg.active(t_rel):
                continue
            pos0, _ = tg.traj.at(t_rel)
            _, az0, _ = enu_to_polar(pos0 - s_enu)
            tau = az0 / 360.0 * self.scan_period_s if self.rotating else 0.005 * self.scan_period_s
            pos, vel = tg.traj.at(t_rel + tau)
            rel = pos - s_enu
            rng_m, az, el = enu_to_polar(rel)
            if not (self.min_range_m <= rng_m <= self.max_range_m) or not (0.0 <= el <= self.max_elev_deg):
                continue
            # Swerling-I: Pd is the *fluctuation-averaged* detection probability for the mean SNR, so Pd is
            # computed from the mean RCS; the reported RCS/SNR of a detection are then one fluctuating draw.
            snr_mean_db = snr90_db + 40 * math.log10(self.r90_m / rng_m) + (tg.rcs_dbsm - RCS_REF_DBSM)
            pd = self.pfa ** (1.0 / (1.0 + 10 ** (snr_mean_db / 10)))
            if rng.random() > pd:
                continue
            fluct_db = 10 * math.log10(max(rng.exponential(1.0), 1e-3))
            rcs_db, snr_db = tg.rcs_dbsm + fluct_db, snr_mean_db + fluct_db
            out.append(self._detection(t_rel + tau, t0_epoch, rng_m, az, el, rcs_db, snr_db, vel, rel, tg.kind, rng))
        for _ in range(rng.poisson(self.fa_per_scan)):
            tau = rng.uniform(0, self.scan_period_s)
            r = rng.uniform(self.min_range_m, self.max_range_m * 0.8)
            az, el = rng.uniform(0, 360), rng.uniform(0, 25)
            out.append(self._detection(t_rel + tau, t0_epoch, r, az, el, rng.uniform(-35, -15), rng.uniform(8, 14),
                                       np.zeros(3), np.array([1.0, 0, 0]), "clutter", rng))
        return out

    def _detection(self, t_rel: float, t0_epoch: float, r: float, az: float, el: float, rcs_db: float, snr_db: float,
                   vel: np.ndarray, rel: np.ndarray, kind: str, rng: np.random.Generator) -> Detection:
        s = self.sensor
        scale = float(np.clip(math.sqrt(self.snr90_lin / max(10 ** (snr_db / 10), 1e-6)), 0.7, 2.5))
        r_n = max(0.0, r + rng.normal(0, s.sigma_range_m * scale))
        az_n = (az + rng.normal(0, s.sigma_az_deg * scale)) % 360.0
        el_n = float(np.clip(el + rng.normal(0, s.sigma_el_deg * scale), -90, 90))
        unit = rel / max(float(np.linalg.norm(rel)), 1e-9)
        v_r = float(np.dot(vel, unit)) + float(rng.normal(0, 0.3))
        md_iq = md_prf = None
        if rng.random() < self.md_probability:
            table: dict[str, Callable[..., Any]] = {"drone": synth_multirotor, "bird": synth_bird}
            fn = table.get(kind, synth_clutter)
            snr_md = float(np.clip(snr_db, 3.0, 25.0))
            md_iq = encode_iq(fn(rng, self.md_samples, self.md_prf_hz, self.fc_hz, v_r, snr_md))
            md_prf = self.md_prf_hz
        return Detection(sensor_id=s.id, t=t0_epoch + t_rel, range_m=float(r_n), azimuth_deg=float(az_n),
                         elevation_deg=el_n, radial_velocity_mps=float(np.clip(v_r, -999, 999)),
                         rcs_dbsm=float(np.clip(rcs_db + rng.normal(0, 1.0), -99, 99)),
                         snr_db=float(np.clip(snr_db, -99, 199)), md_iq_b64=md_iq, md_prf_hz=md_prf)


@dataclass
class FixModel:
    """Position-fix sensor (geodetic output): Remote ID, RF geolocation, EO/IR triangulated fix."""

    sensor: SensorConfig
    rate_hz: float
    sigma_h_m: float
    sigma_v_m: float
    max_range_m: float
    pd: float = 0.9
    only_cooperative: bool = False  # Remote ID: only cooperative drones transmit
    drones_only: bool = True  # RF: only emitters with a control link
    send_serial: bool = False

    def sample(self, t_rel: float, t0_epoch: float, targets: list[Target], frame: LocalFrame,
               rng: np.random.Generator) -> list[Detection]:
        s = self.sensor
        s_enu = frame.to_enu(s.lat, s.lon, s.alt_m)
        out: list[Detection] = []
        for tg in targets:
            if not tg.active(t_rel):
                continue
            if self.only_cooperative and not tg.cooperative:
                continue
            if self.drones_only and tg.kind != "drone":
                continue
            pos, _ = tg.traj.at(t_rel)
            if float(np.linalg.norm(pos - s_enu)) > self.max_range_m or rng.random() > self.pd:
                continue
            noisy = pos + rng.normal(0, [self.sigma_h_m, self.sigma_h_m, self.sigma_v_m])
            lat, lon, alt = frame.to_geodetic(noisy)
            out.append(Detection(sensor_id=s.id, t=t0_epoch + t_rel, lat=float(lat), lon=float(lon),
                                 alt_m=float(alt), sigma_h_m=self.sigma_h_m, sigma_v_m=self.sigma_v_m,
                                 external_id=tg.serial if self.send_serial else None))
        return out
