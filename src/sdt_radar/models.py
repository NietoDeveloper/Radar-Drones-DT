"""Domain and wire models.

Wire/API models are pydantic (strict validation at the edge). Hot-path structures used by the tracker
are plain dataclasses holding numpy arrays.
"""

from __future__ import annotations

    tentative = "tentative"
    confirmed = "confirmed"
    coasting = "coasting"
    lost = "lost"


    model_config = ConfigDict(extra="
    sensor_id: str = Field(min_length=1, max_length=64)
    t: float  # UNIX epoch seconds (UTC) of the measurement
    range_m: float | None = Field(None, ge=0, le=1_000_000)
    azimuth_deg: float | None = Field(None, ge=-720, le=720)
    elevation_deg: float | None = Field(None, ge=-90, le=90)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    alt_m: float | None = Field(None, ge=-1000, le=100_000)
    sigma_h_m: float | None = Field(None, gt=0, le=10_000)
    sigma_v_m: float | None = Field(None, gt=0, le=10_000)
    radial_velocity_mps: float | None = Field(None, ge=-1000, le=1000)
    rcs_dbsm: float | None = Field(None, ge=-100, le=100)
    snr_db: float | None = Field(None, ge=-100, le=200)
    external_id: str | None = Field(None, max_length=64)
    md_prf_hz: float | None = Field(None, gt=0, le=1_000_000)
    md_iq_b64: str | None = Field(None, max_length=MAX_MD_SAMPLES * 11)

    @field_validator("t")
    @classmethod
    def _plausible_time(cls, v: float) -> float:
        if not (946_684_800.0 <= v <= 4_102_444_800.0):  # 2000-01-01 .. 2100-01-01
            raise ValueError("t must be UNIX epoch seconds between 2000 and 2100")
        return v

    @model_validator(mode="after")
    def _one_geometry(self) -> Detection:
        polar = (self.range_m, self.azimuth_deg, self.elevation_deg)
        geo = (self.lat, self.lon, self.alt_m)
        has_polar, has_geo = all(v is not None for v in polar), all(v is not None for v in geo)
        if any(v is not None for v in polar) and not has_polar:
            raise ValueError("polar measurement needs range_m, azimuth_deg and elevation_deg together")
        if any(v is not None for v in geo) and not has_geo:
            raise ValueError("geodetic measurement needs lat, lon and alt_m together")
        if has_polar == has_geo:
            raise ValueError("provide exactly one of: polar (range/azimuth/elevation) or geodetic (lat/lon/alt)")
        if (self.md_iq_b64 is None) != (self.md_prf_hz is None):
            raise ValueError("md_iq_b64 and md_prf_hz must be provided together")
        return self

    @property
    def is_polar(self) -> bool:
        return self.range_m is not None


# --------------------------------------------------------------------------- internal structures


@dataclass(slots=True)
class Measurement:
    """Detection converted to the local E