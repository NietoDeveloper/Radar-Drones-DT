"""Scenarios (targets + sensors), detection-stream generation and an offline runner with scoring."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import Settings, SiteConfig
from ..geo import LocalFrame
from ..models import AlertLevel, Detection, SensorConfig, SensorKind, Zone
from ..pipeline import Pipeline
from .metrics import Score, evaluate_snapshot
from .sensors import FixModel, RadarModel
from .targets import Target, make_bird, make_drone

    def settings(self, **overrides: object) -> Settings:
        data = {"site": self.site, "sensors": self.sensor_configs(), "zones": self.zones,
                "storage": {"kind": "memory"}}
        data.update(overrides)
        return Settings.model_validate(data)

    def truth(self, t_rel: float, warmup_s: float = 0.0) -> list[tuple[str, str, np.ndarray]]:
        out = []
        for tg in self.targets:
            if tg.active(t_rel) and t_rel >= tg.t_start + warmup_s:
                out.append((tg.target_id, tg.kind, tg.traj.at(t_rel)[0]))
        return out


def generate(scn: Scenario) -> list[Detection]:
    """Full detection stream, sorted by measurement time."""
    rng = np.random.default_rng(scn.seed + 1000)
    frame = scn.frame
    dets: list[Detection] = []
    for r in scn.radars:
        k = 0
        while k * r.scan_period_s < scn.duration_s:
            dets += r.scan(k * r.scan_period_s, scn.t0_epoch, scn.targets, frame, rng)
            k += 1
    for f in scn.fixes:
        k = 0
        while k / f.rate_hz < scn.duration_s:
            dets += f.sample(k / f.rate_hz, scn.t0_epoch, scn.targets, frame, rng)
            k += 1
    dets.sort(key=lambda d: d.t)
    return dets


def _site() -> SiteConfig:
    return SiteConfig(lat=4.7110, lon=-74.0721, alt_m=2600.0)


def _sensor(sid: str, kind: SensorKind, frame: LocalFrame, east_m: float = 0.0, north_m: float = 0.0, alt_m: float = 5.0,
            **kw: float) -> SensorConfig:
    lat, lon, alt = frame.to_geodetic(np.array([east_m, north_m, alt_m]))
    return SensorConfig(id=sid, kind=kind, lat=float(lat), lon=float(lon), alt_m=float(alt) + 0.0, **kw)


def perimeter_scenario(seed: int = 1, duration_s: float = 150.0, n_drones: int = 6, n_birds: int = 15) -> Scenario:
    """Campus/prison perimeter: FMCW radar + AESA panel + Remote ID receiver; drones, birds, a protected zone."""
    rng = np.random.default_rng(seed)
    site = _site()
    frame = LocalFrame(site.lat, site.lon, site.alt_m)
    radars = [
        RadarModel(_sensor("fmcw-1", SensorKind.radar_fmcw, frame, 0, 0, 8, sigma_range_m=4.0, sigma_az_deg=1.2,
                           sigma_el_deg=2.5, max_range_m=3500), r90_m=2500, scan_period_s=1.0, fa_per_scan=1.5),
        RadarModel(_sensor("aesa-1", SensorKind.radar_aesa, frame, 1200, 300, 10, sigma_range_m=3.0, sigma_az_deg=0.5,
                           sigma_el_deg=0.8, max_range_m=5500), r90_m=3500, scan_period_s=0.5, rotating=False,
                   fa_per_scan=1.0),
    ]
    fixes = [FixModel(_sensor("rid-1", SensorKind.remote_id, frame, 0, 0, 3, sigma_range_m=4.0), rate_hz=1.0,
                      sigma_h_m=4.0, sigma_v_m=6.0, max_range_m=3000, only_cooperative=True, send_serial=True)]
    targets: list[Target] = []
    for i in range(n_drones):
        targets.append(make_drone(rng, i, duration_s, 0.1, approach=(i % 2 == 0), bearing_deg=float(rng.uniform(0, 360)),
                                  start_range_m=float(rng.uniform(1200, 2200)), cooperative=(i % 3 == 0)))
    for i in range(n_birds):
        targets.append(make_bird(rng, i, duration_s, 0.1, max_range_m=2500))
    zone = Zone(id="core", name="Protected core", kind="circle", center_lat=site.lat, center_lon=site.lon,
                radius_m=400.0, min_alt_m=-1000, max_alt_m=100000, level=AlertLevel.critical)
    return Scenario("perimeter", duration_s, site, radars, fixes, targets, [zone], seed)


def swarm_scenario(n_targets: int = 300, seed: int = 2, duration_s: float = 60.0) -> Scenario:
    """Stress test: hundreds of simultaneous tracks over a pulse-Doppler radar (no micro-Doppler payload)."""
    rng = np.random.default_rng(seed)
    site = _site()
    frame = LocalFrame(site.lat, site.lon, site.alt_m)
    radar = RadarModel(_sensor("pd-1", SensorKind.radar_pulse_doppler, frame, 0, 0, 10, sigma_range_m=8.0,
                               sigma_az_deg=0.6, sigma_el_deg=1.0, max_range_m=15000), r90_m=9000,
                       scan_period_s=2.0, fa_per_scan=3.0, md_probability=0.0)
    targets = [make_drone(rng, i, duration_s, 0.2, approach=False, bearing_deg=float(rng.uniform(0, 360)),
                          start_range_m=float(rng.uniform(1500, 7000)), cooperative=False) for i in range(n_targets)]
    return Scenario(f"swarm-{n_targets}", duration_s, site, [radar], [], targets, [], seed)


def run_scenario(scn: Scenario, settings: Settings | None = None, pipeline: Pipeline | None = None,
                 step_s: float = 0.5, eval_every_s: float = 1.0, warmup_s: float = 15.0,
                 detections: list[Detection] | None = None, gate_m: float = 100.0) -> tuple[Pipeline, Score, list]:
    """Run a scenario through a pipeline in data time (faster than real time) and score the result."""
    pipe = pipeline or Pipeline(settings or scn.settings())
    pipe.start()
    dets = detect