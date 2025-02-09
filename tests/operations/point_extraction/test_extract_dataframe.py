import pathlib

import numpy as np
import pandas as pd
import xarray as xr
from numpy.testing import assert_equal
from shapely.geometry import Point

from emsarray.operations import point_extraction


def test_extract_dataframe(
    datasets: pathlib.Path,
) -> None:
    num_points = 10
    names = [f'{chr(97 + i)}{i + 1}' for i in range(num_points)]
    rs = np.random.sample(num_points) * 3
    θs = np.random.sample(num_points) * 2 * np.pi
    xs = np.cos(θs) * rs
    ys = np.sin(θs) * rs
    points_df = pd.DataFrame({'name': names, 'lon': xs, 'lat': ys})

    in_dataset = xr.open_dataset(datasets / 'ugrid_mesh2d.nc')
    point_dataset = point_extraction.extract_dataframe(
        in_dataset, points_df, coordinate_columns=('lon', 'lat'))

    # There should be a new dimension named 'points'
    # with the same size as the number of rows in the CSV
    assert 'point' in point_dataset.dims
    assert point_dataset.dims['point'] == num_points

    # All the columns from the CSV should have been merged in
    assert_equal(points_df['name'], point_dataset['name'].values)
    assert_equal(points_df['lon'], point_dataset['lon'].values)
    assert_equal(points_df['lat'], point_dataset['lat'].values)

    # The new point coordinate variables should have the relevant CF attributes
    assert point_dataset['lon'].attrs == {
        "long_name": "longitude",
        "units": "degrees_east",
        "standard_name": "longitude",
    }
    assert point_dataset['lat'].attrs == {
        "long_name": "latitude",
        "units": "degrees_north",
        "standard_name": "latitude",
    }

    # The values should be extracted from the dataset, one per point
    assert 'values' in point_dataset.data_vars
    values = point_dataset.data_vars['values']
    assert values.dims == ('point',)
    print(values.values)
    assert_equal(values.values, [
        in_dataset.ems.select_point(Point(row['lon'], row['lat']))['values'].values
        for i, row in points_df.iterrows()
    ])
