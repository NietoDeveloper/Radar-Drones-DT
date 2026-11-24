"""Reference catalogue of sensor types useful for drone detection (planning aid, not a vendor datasheet)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RadarClass:
    key: str
    name: str
    typical_range_km: str
    strengths: str
    weaknesses: str
    best_for: str


RADAR_CATALOG: tuple[RadarClass, ...] = (
    RadarClass("radar_fmcw", "FMCW (frequency-modulated continuous wave)", "0.5 - 3",
               "No near-range blind zone, compact, low power, fine range resolution",
               "Shorter range; waveform leakage and clutter need careful processing",
               "Perimeters, prisons, campuses, critical infrastructure"),
    RadarClass("radar_pulse_doppler", "Pulse-Doppler", "5 - 20",
               "Long range, strong ground-clutter rejection via Doppler filtering",
               "Near-range blind zone (eclipsing), larger and costlier",
               "Airports, defence, wide-area surveillance"),
    RadarClass("radar_aesa", "Phased array (AESA / MESA)", "1 - 10",
               "Electronic scanning, simultaneous multi-target tracking, very high update rate, 360 degrees with panels",
               "Cost, calibration, thermal management",
               "Continuous 360-degree tracking of many targets"),
    RadarClass("micro_doppler", "Micro-Doppler analysis (a processing mode)", "n/a",
               "Rotor-blade / wing-beat signature separates drones from birds; cuts false alarms",
               "Needs dwell time and adequate SNR; training data per radar band",
               "Classification stage on top of any coherent radar"),
    RadarClass("radar_passive", "Passive radar (DVB-T / 4G / 5G illuminators)", "2 - 10+",
               "Non-emitting, covert, cheap, reuses existing infrastructure",
               "Depends on illuminator geometry and coverage; lower accuracy",
               "Low-cost dense networks, combined with acoustic / RF sensors"),
    RadarClass("rf", "RF detection / direction finding", "1 - 10",
               "Detects control/video links, can identify protocol and sometimes the operator position",
               "Blind to autonomous / link-silent drones", "Complement to radar"),
    RadarClass("remote_id", "Remote ID receiver", "~1 - 3",
               "Cooperative drones broadcast identity and position", "Only cooperative targets; spoofable",
               "Identity and compliance checks"),
    RadarClass("eo_ir", "EO / IR cameras (PTZ)", "1 - 3",
               "Visual confirmation, evidence, classification", "Weather/lighting dependent, narrow field of view",
               "Cued confirmation of radar tracks"),
    RadarClass("acoustic", "Acoustic arrays", "0.3 - 1",
               "Passive, cheap, works behind obstacles", "Short range, noise-sensitive", "Dense local coverage"),
)
