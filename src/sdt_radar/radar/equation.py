"""Radar range equation helpers for sizing a sensor against a drone-class target (RCS ~ 0.01 m²)."""

from __future__ import annotations

import math

C0 = 299_792_458.0
K_BOLTZMANN = 1.380649e-23
RCS_DJI_CLASS_M2 = 0.01  # -20 dBsm


def _lin(db: float) -> float:
    return 10.0 ** (db / 10.0)


def radar_range_m(peak_power_w: float, gain_dbi: float, freq_hz: float, rcs_m2: float, min_snr_db: float,
                  bandwidth_hz: float, noise_figure_db: float = 5.0, losses_db: float = 4.0,
                  integration_gain_db: float = 0.0, temp_k: float = 290.0) -> float:
    """Maximum range (m) at which SNR >= ``min_snr_db`` (monostatic, free space, single target).

    R^4 = Pt G^2 lambda^2 sigma Gint / ((4 pi)^3 k T B F L SNR_min)

    ``peak_power_w`` is the *effective* transmit power over the coherent dwell: for FMCW use the average
    power; for pulsed radars use peak power x duty cycle x pulses integrated (or fold the gain into
    ``integration_gain_db``).
    """
    lam = C0 / freq_hz
    g = _lin(gain_dbi)
    num = peak_power_w * g * g * lam * lam * rcs_m2 * _lin(integration_gain_db)
    den = ((4 * math.pi) ** 3 * K_BOLTZMANN * temp_k * bandwidth_hz * _lin(noise_figure_db)
           * _lin(losses_db) * _lin(min_snr_db))
    return float((num / den) ** 0.25)


def snr_db_at_range(range_m: float, peak_power_w: float, gain_dbi: float, freq_hz: float, rcs_m2: float,
                    bandwidth_hz: float, noise_figure_db: float = 5.0, losses_db: float = 4.0,
                    integration_gain_db: float = 0.0, temp_k: float = 290.0) -> float:
    r_ref = radar_range_m(peak_power_w, gain_dbi, freq_hz, rcs_m2, 0.0, bandwidth_hz, noise_figure_db,
                          losses_db, integration_gain_db, temp_k)
    return 40.0 * math.log10(r_ref / range_m)  # SNR falls 40 dB per decade of range


def range_resolution_m(bandwidth_hz: float) -> float:
    """Range resolution of a swept/modulated waveform: c / (2 B)."""
    return C0 / (2.0 * bandwidth_hz)


def velocity_resolution_mps(freq_hz: float, dwell_s: float) -> float:
    """Doppler velocity resolution for a coherent dwell: lambda / (2 T)."""
    return (C0 / freq_hz) / (2.0 * dwell_s)
