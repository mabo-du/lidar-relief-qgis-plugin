import pytest

from lidar_relief.e4mstp_settings import E4MstpSettings


def test_canonical_settings_preserve_historical_e4mstp_values():
    assert E4MstpSettings().as_dict() == {
        "openness_radius": 10,
        "num_directions": 16,
        "ld_min_radius": 10,
        "ld_max_radius": 20,
        "ld_angular_resolution": 15.0,
        "ld_observer_height": 1.7,
        "mstp_local_radius": 3,
        "mstp_meso_radius": 20,
        "mstp_broad_radius": 100,
        "tile_size": 1024,
    }
    assert E4MstpSettings().halo_size == 100


def test_custom_settings_validate_radius_ordering():
    custom = E4MstpSettings(
        openness_radius=25,
        mstp_local_radius=5,
        mstp_meso_radius=30,
        mstp_broad_radius=150,
    )
    custom.validate()
    assert custom.halo_size == 150
    with pytest.raises(ValueError, match="MSTP radii"):
        E4MstpSettings(
            mstp_local_radius=30,
            mstp_meso_radius=20,
            mstp_broad_radius=100,
        ).validate()


def test_custom_settings_validate_local_dominance_ordering():
    with pytest.raises(ValueError, match="Local Dominance"):
        E4MstpSettings(ld_min_radius=20, ld_max_radius=10).validate()
