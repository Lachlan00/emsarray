from __future__ import annotations

import itertools
import json
from typing import Type

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from matplotlib.figure import Figure
from shapely.geometry.polygon import Polygon, orient

from emsarray.formats import get_file_format
from emsarray.formats.arakawa_c import c_mask_from_centres
from emsarray.formats.shoc import ArakawaCGridKind, ShocStandard
from tests.utils import DiagonalShocGrid, ShocGridGenerator, ShocLayerGenerator


def make_dataset(
    *,
    k_size: int = 5,
    j_size: int,
    i_size: int,
    time_size: int = 4,
    grid_type: Type[ShocGridGenerator] = DiagonalShocGrid,
    corner_size: int = 0,
) -> xr.Dataset:
    """
    Make a dummy SHOC simple dataset of a particular size.
    It will have a sheared grid of points located near (0, 0),
    with increasing j moving north east, and increasing i moving south east.

    For a grid with j_size=5, i_size=9, the centre longitude-latitude will be:

    * index (0, 0): (0.1, 0.9),
    * index (0, 1): (0.2, 0.8),
    * index (0, 8): (0.9, 0.1)
    * index (1, 0): (0.2, 0.10)
    * index (1, 8): (0.10, 0.2)
    * index (4, 0): (0.5, 0.13)

    Three data variables will be made: botz, eta, and temp.
    Each will be filled with random data.
    There will be a one-cell border around the edge of the dataset where all
    data variables will be nans.

    The (i=0, j=j_size) corner will not have any coordinates in a 4x4 box.
    The (i=i_size, j=j_size) corner will have coordinates,
    but data variables will be masked off
    """
    coordinate_centre_mask = np.full((j_size, i_size), True)
    # Cut a chunk out of the corner where the coordinates will not be defined.
    if corner_size > 1:
        coordinate_centre_mask[-(corner_size - 1):, :+(corner_size - 1)] = False

    # SHOC files have a 1-cell border around the outside where the cells have
    # coordinates, but no data.
    wet_centre_mask = np.full((j_size, i_size), True)
    if corner_size > 0:
        wet_centre_mask[-corner_size:, :+corner_size] = False
        wet_centre_mask[-corner_size:, -corner_size:] = False
    wet_centre_mask[:+1, :] = False
    wet_centre_mask[-1:, :] = False
    wet_centre_mask[:, :+1] = False
    wet_centre_mask[:, -1:] = False
    wet_mask = c_mask_from_centres(wet_centre_mask, {
        ArakawaCGridKind.face: ('j_centre', 'i_centre'),
        ArakawaCGridKind.back: ('j_back', 'i_back'),
        ArakawaCGridKind.left: ('j_left', 'i_left'),
        ArakawaCGridKind.node: ('j_node', 'i_node'),
    })

    # These DataArrays are the long/lats of the grid corners. The centres are
    # derived from these by averaging the surrounding four corners.
    grid = grid_type(j=j_size, i=i_size, face_mask=coordinate_centre_mask)
    layers = ShocLayerGenerator(k=k_size)

    t = xr.DataArray(
        # Note: Using pd.date_range() directly here will lead to strange
        # behaviours, where the `record` dimension becomes a data variable with
        # a datetime64 dtype. Using a list of datetimes instead seems to avoid
        # this, resulting in record simply being a dimension.
        data=list(pd.date_range("2021-11-11", periods=time_size)),
        dims=["record"],
        attrs={
            "long_name": "Time",
            "standard_name": "time",
            "coordinate_type": "time",
        },
    )
    # Note: xarray will reformat this in to 1990-01-01T00:00:00+10:00, which
    # EMS fails to parse. There is no way around this using xarray natively,
    # you have to adjust it with nctool after saving it.
    t.encoding["units"] = "days since 1990-01-01 00:00:00 +10"

    botz = xr.DataArray(
        data=np.random.random((j_size, i_size)) * 10 + 50,
        dims=wet_mask["face_mask"].dims,
        attrs={
            "units": "metre",
            "long_name": "Z coordinate at sea-bed at cell centre",
            "standard_name": "depth",
            "positive": "down",
            "outside": "9999",
            "missing_value": -99.,
        }
    ).where(wet_mask.data_vars["face_mask"])
    botz.values[1, 1] = -99.

    eta = xr.DataArray(
        data=np.random.normal(0, 0.2, (time_size, j_size, i_size)),
        dims=["record", *wet_mask["face_mask"].dims],
        attrs={
                "units": "metre",
                "long_name": "Surface elevation",
                "standard_name": "sea_surface_height_above_geoid",
            }
    ).where(wet_mask.data_vars["face_mask"])
    temp = xr.DataArray(
        data=np.random.normal(12, 0.5, (time_size, k_size, j_size, i_size)),
        dims=["record", "k_centre", *wet_mask["face_mask"].dims],
        attrs={
            "units": "degrees C",
            "long_name": "Temperature",
        },
    ).where(wet_mask.data_vars["face_mask"])

    u1 = xr.DataArray(
        data=np.random.normal(0, 2, (time_size, k_size, j_size, i_size + 1)),
        dims=["record", "k_centre", *wet_mask.data_vars["left_mask"].dims],
        attrs={
            "units": "metre second-1",
            "long_name": "I component of current at left face",
        }
    )
    u2 = xr.DataArray(
        data=np.random.normal(0, 2, (time_size, k_size, j_size + 1, i_size)),
        dims=["record", "k_centre", *wet_mask.data_vars["back_mask"].dims],
        attrs={
            "units": "metre per second",
            "long_name": "I component of current at back face",
        }
    )
    flag = xr.DataArray(
        data=np.random.randint(0, 256, (time_size, k_size, j_size + 1, i_size + 1)),
        dims=["record", "k_centre", *wet_mask.data_vars["node_mask"].dims],
        attrs={"long_name": "SHOC masking flags"},
    )

    dataset = xr.Dataset(
        data_vars={
            **layers.standard_vars,
            **grid.standard_vars,
            "botz": botz,
            "t": t,
            "eta": eta,
            "temp": temp,
            "u1": u1,
            "u2": u2,
            "flag": flag,
        },
        attrs={
            "title": "Example SHOC dataset",
            "ems_version": "v1.2.3 fake",
            "Conventions": "CMR/Timeseries/SHOC",
            "nce1": j_size,
            "nce2": i_size,
            "nfe1": j_size + 1,
            "nfe2": i_size + 1,
            "gridtype": "NUMERICAL",
        },
    )
    dataset.encoding["unlimited_dims"] = {"record"}
    return dataset


def test_make_dataset():
    dataset = make_dataset(j_size=5, i_size=9, corner_size=2)

    # Check that this is recognised as a ShocSimple dataset
    assert get_file_format(dataset) is ShocStandard

    # Check that the correct format helper is made
    assert isinstance(dataset.ems, ShocStandard)

    # Check the coordinate generation worked.
    x_centre = dataset["x_centre"]
    y_centre = dataset["y_centre"]
    assert x_centre[0, 0] == pytest.approx(0.1)
    assert x_centre[0, 1] == pytest.approx(0.2)
    assert x_centre[0, 8] == pytest.approx(0.9)
    assert x_centre[1, 0] == pytest.approx(0.2)
    assert y_centre[0, 0] == pytest.approx(0.9)
    assert y_centre[0, 1] == pytest.approx(0.8)
    assert y_centre[0, 8] == pytest.approx(0.1)
    assert y_centre[1, 0] == pytest.approx(1.0)

    # Check the coordinate generation worked.
    x_grid = dataset["x_grid"]
    y_grid = dataset["y_grid"]
    assert x_grid[0, 0] == pytest.approx(0.0)
    assert x_grid[0, 1] == pytest.approx(0.1)
    assert x_grid[0, 9] == pytest.approx(0.9)
    assert x_grid[1, 0] == pytest.approx(0.1)
    assert y_grid[0, 0] == pytest.approx(0.9)
    assert y_grid[0, 1] == pytest.approx(0.8)
    assert y_grid[0, 8] == pytest.approx(0.1)
    assert y_grid[0, 9] == pytest.approx(0.0)
    assert y_grid[1, 0] == pytest.approx(1.0)


def test_varnames():
    dataset = make_dataset(j_size=10, i_size=10)
    assert dataset.ems.get_depth_name() == 'z_centre'
    assert dataset.ems.get_all_depth_names() == ['z_centre', 'z_grid']
    assert dataset.ems.get_time_name() == 't'


def test_polygons():
    dataset = make_dataset(j_size=10, i_size=20, corner_size=5)

    polygons = dataset.ems.polygons
    # Should be one item for every cell in the shape
    assert polygons.size == 10 * 20

    polygon_grid = polygons.reshape((10, 20))

    # Check some specific polygons
    actual = polygon_grid[1, 1]
    expected = orient(Polygon([
        (0.2, 2.0), (0.3, 2.1), (0.4, 2.0), (0.3, 1.9), (0.2, 2.0),
    ]))
    assert actual.equals_exact(expected, 1e-6)

    actual = polygon_grid[-2, -6]
    expected = orient(Polygon([(2.2, 1.4), (2.3, 1.5), (2.4, 1.4), (2.3, 1.3), (2.2, 1.4)]))
    assert actual.equals_exact(expected, 1e-6)


def test_face_centres():
    # SHOC standard face centres are taken directly from the coordinates,
    # not calculated from polygon centres.
    dataset = make_dataset(j_size=10, i_size=20, corner_size=3)
    helper: ShocStandard = dataset.ems

    face_centres = helper.face_centres
    lons = dataset['x_centre'].values
    lats = dataset['y_centre'].values
    for j in range(dataset.dims['j_centre']):
        for i in range(dataset.dims['i_centre']):
            lon = lons[j, i]
            lat = lats[j, i]
            linear_index = helper.ravel_index((ArakawaCGridKind.face, j, i))
            np.testing.assert_equal(face_centres[linear_index], [lon, lat])


def test_make_geojson_geometry():
    dataset = make_dataset(j_size=10, i_size=10, corner_size=3)
    out = json.dumps(dataset.ems.make_geojson_geometry())
    assert isinstance(out, str)


def test_ravel():
    dataset = make_dataset(j_size=5, i_size=7)
    helper: ShocStandard = dataset.ems

    for ravelled, (j, i) in enumerate(itertools.product(range(5), range(7))):
        index = (ArakawaCGridKind.face, j, i)
        assert helper.ravel_index(index) == ravelled
        assert helper.unravel_index(ravelled) == index
        assert helper.unravel_index(ravelled, ArakawaCGridKind.face) == index


def test_ravel_left():
    dataset = make_dataset(j_size=5, i_size=7)
    helper: ShocStandard = dataset.ems

    for ravelled, (j, i) in enumerate(itertools.product(range(5), range(8))):
        index = (ArakawaCGridKind.left, j, i)
        assert helper.ravel_index(index) == ravelled
        assert helper.unravel_index(ravelled, ArakawaCGridKind.left) == index


def test_ravel_back():
    dataset = make_dataset(j_size=5, i_size=7)
    helper: ShocStandard = dataset.ems

    for ravelled, (j, i) in enumerate(itertools.product(range(6), range(7))):
        index = (ArakawaCGridKind.back, j, i)
        assert helper.ravel_index(index) == ravelled
        assert helper.unravel_index(ravelled, ArakawaCGridKind.back) == index


def test_ravel_grid():
    dataset = make_dataset(j_size=5, i_size=7)
    helper: ShocStandard = dataset.ems

    for ravelled, (j, i) in enumerate(itertools.product(range(6), range(8))):
        index = (ArakawaCGridKind.node, j, i)
        assert helper.ravel_index(index) == ravelled
        assert helper.unravel_index(ravelled, ArakawaCGridKind.node) == index


def test_grid_kinds():
    dataset = make_dataset(j_size=3, i_size=5)
    helper: ShocStandard = dataset.ems

    assert helper.grid_kinds == frozenset({
        ArakawaCGridKind.face,
        ArakawaCGridKind.left,
        ArakawaCGridKind.back,
        ArakawaCGridKind.node,
    })

    assert helper.default_grid_kind == ArakawaCGridKind.face


def test_grid_kind_and_size():
    dataset = make_dataset(j_size=5, i_size=7)
    helper: ShocStandard = dataset.ems

    grid_kind, size = helper.get_grid_kind_and_size(dataset.data_vars['temp'])
    assert grid_kind is ArakawaCGridKind.face
    assert size == 5 * 7

    grid_kind, size = helper.get_grid_kind_and_size(dataset.data_vars['u1'])
    assert grid_kind is ArakawaCGridKind.left
    assert size == 5 * 8

    grid_kind, size = helper.get_grid_kind_and_size(dataset.data_vars['u2'])
    assert grid_kind is ArakawaCGridKind.back
    assert size == 6 * 7

    grid_kind, size = helper.get_grid_kind_and_size(dataset.data_vars['flag'])
    assert grid_kind is ArakawaCGridKind.node
    assert size == 6 * 8


@pytest.mark.parametrize(
    ['index', 'selector'],
    (
        [(ArakawaCGridKind.face, 3, 4), {'j_centre': 3, 'i_centre': 4}],
        [(ArakawaCGridKind.left, 5, 6), {'j_left': 5, 'i_left': 6}],
        [(ArakawaCGridKind.back, 7, 8), {'j_back': 7, 'i_back': 8}],
        [(ArakawaCGridKind.node, 9, 10), {'j_node': 9, 'i_node': 10}],
    ),
)
def test_selector_for_index(index, selector):
    dataset = make_dataset(j_size=5, i_size=7)
    helper: ShocStandard = dataset.ems
    assert selector == helper.selector_for_index(index)


# These select_index tests are not specifically about SHOC,
# they are more about how select_index behaves with multiple grid kinds.
def test_select_index_face():
    dataset = make_dataset(time_size=4, k_size=5, j_size=5, i_size=9)
    helper: ShocStandard = dataset.ems
    face = helper.select_index((ArakawaCGridKind.face, 3, 4))

    assert set(face.data_vars.keys()) == {
        # These are the data variables we expect to see
        'botz', 'eta', 'temp',
        # These coordinates variables are also included in data_vars
        # because of how xarray handles multidimensional coordinates
        'x_centre', 'y_centre',
    }
    assert face.dims == {'record': 4, 'k_centre': 5}
    assert face['x_centre'].values == dataset['x_centre'].values[3, 4]
    assert face['y_centre'].values == dataset['y_centre'].values[3, 4]


def test_select_index_edge():
    dataset = make_dataset(time_size=4, k_size=5, j_size=5, i_size=9)
    helper: ShocStandard = dataset.ems

    left = helper.select_index((ArakawaCGridKind.left, 3, 4))
    assert set(left.data_vars.keys()) == {
        # This is the only data variable we expect to see,
        # as it is the only one defined on left edges.
        'u1',
        # These coordinates variables are also included in data_vars
        # because of how xarray handles multidimensional coordinates
        'x_left', 'y_left'
    }
    assert left.dims == {'record': 4, 'k_centre': 5}

    back = helper.select_index((ArakawaCGridKind.back, 3, 4))
    assert set(back.data_vars.keys()) == {
        # This is the only data variable we expect to see,
        # as it is the only one defined on back edges.
        'u2',
        # These coordinates variables are also included in data_vars
        # because of how xarray handles multidimensional coordinates
        'x_back', 'y_back'
    }
    assert back.dims == {'record': 4, 'k_centre': 5}


def test_select_index_grid():
    dataset = make_dataset(time_size=4, k_size=5, j_size=5, i_size=9)
    helper: ShocStandard = dataset.ems

    node = helper.select_index((ArakawaCGridKind.node, 3, 4))
    assert set(node.data_vars.keys()) == {
        # This is the only data variable we expect to see,
        # as it is the only one defined on the node.
        'flag',
        # These coordinates variables are also included in data_vars
        # because of how xarray handles multidimensional coordinates
        'x_grid', 'y_grid'
    }
    assert node.dims == {'record': 4, 'k_centre': 5}


def test_values():
    dataset = make_dataset(j_size=10, i_size=20, corner_size=5)
    eta = dataset.data_vars["eta"].isel(record=0)
    values = dataset.ems.make_linear(eta)

    # There should be one value per cell polygon
    assert len(values) == len(dataset.ems.polygons)

    # The values should be in a specific order
    assert np.allclose(values, eta.values.ravel(), equal_nan=True)


@pytest.mark.matplotlib
def test_plot_on_figure():
    # Not much to test here, mostly that it doesn't throw an error
    dataset = make_dataset(j_size=10, i_size=20)
    surface_temp = dataset.data_vars["temp"].isel(k_centre=-1, record=0)

    figure = Figure()
    dataset.ems.plot_on_figure(figure, surface_temp)

    assert len(figure.axes) == 2
