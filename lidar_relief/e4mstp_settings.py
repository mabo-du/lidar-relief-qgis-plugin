"""Validated e4MSTP controls with backward-compatible canonical defaults."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class E4MstpSettings:
    openness_radius: int = 10
    num_directions: int = 16
    ld_min_radius: int = 10
    ld_max_radius: int = 20
    ld_angular_resolution: float = 15.0
    ld_observer_height: float = 1.7
    mstp_local_radius: int = 3
    mstp_meso_radius: int = 20
    mstp_broad_radius: int = 100
    tile_size: int = 1024

    def validate(self) -> "E4MstpSettings":
        if self.ld_min_radius >= self.ld_max_radius:
            raise ValueError(
                "Local Dominance minimum radius must be smaller than its maximum."
            )
        if not (
            self.mstp_local_radius < self.mstp_meso_radius < self.mstp_broad_radius
        ):
            raise ValueError("MSTP radii must increase from local to meso to broad.")
        if self.openness_radius < 1 or self.num_directions < 4:
            raise ValueError("Openness radius and direction count are too small.")
        if self.ld_angular_resolution <= 0 or self.ld_observer_height <= 0:
            raise ValueError("Local Dominance controls must be positive.")
        if self.tile_size < 256:
            raise ValueError("Tile size must be at least 256 pixels.")
        return self

    @property
    def halo_size(self) -> int:
        return max(
            self.openness_radius,
            self.ld_max_radius,
            self.mstp_broad_radius,
        )

    def as_dict(self) -> dict:
        return asdict(self)
