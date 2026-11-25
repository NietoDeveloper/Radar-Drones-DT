"""Sensor models: a radar (Swerling-I detection, range-dependent noise, clutter, micro-Doppler dwell) and
generic position-fix sources (Remote ID, RF geolocation, EO/IR triangulation).

Detection model: the radar is specified by ``r90_m`` — the range at which a 0.01 m² (-20 dBsm) target
is detected with Pd = 0.9 at the configured Pfa. SNR then scales as ``-40 log10(R)`` and with RCS; Pd
follows the Swerling-I relation ``Pd = Pfa ** (1 / (1 + SNR))``. This is a planning-grade model, not a
waveform-level simulation.
""")) > self.max_range_m or rng.random() > self.pd:
                continue
            noisy = pos + rng.normal(0, [self.sigma_h_m, self.sigma_h_m, self.sigma_v_m])
            lat, lon, alt = frame.to_geodetic(noisy)
            out.append(Detection(sensor_id=s.id, t=t0_epoch + t_rel, lat=float(lat), lon=float(lon),
                                 alt_m=float(alt), sigma_h_m=self.sigma_h_m, sigma_v_m=self.sigma_v_m,
                                 external_id=tg.serial if self.send_serial else None))
        return out
