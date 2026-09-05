"""Геометрия хранится в WGS84; площадь считается геодезически на сервере."""
import math
from pyproj import Geod
from shapely.geometry import shape, mapping
from shapely import orient_polygons


def validate_geometry(value):
    if not isinstance(value,dict):
        raise ValueError('Нарисуйте контур или загрузите GeoJSON.')
    if value.get('type') == 'FeatureCollection':
        features = value.get('features',[])
        if len(features) != 1:
            raise ValueError('В файле должен быть ровно один участок.')
        value = features[0]
    if value.get('type') == 'Feature':
        value = value.get('geometry')
    geom = shape(value)
    if geom.geom_type not in ('Polygon','MultiPolygon') or geom.is_empty or not geom.is_valid:
        raise ValueError('Нужен корректный Polygon/MultiPolygon без самопересечений.')
    from shapely import get_coordinates
    coords = get_coordinates(geom)
    if len(coords)>10000 or any(not math.isfinite(float(x)) for p in coords for x in p):
        raise ValueError('Слишком сложная или некорректная геометрия.')
    west,south,east,north = geom.bounds
    if west < -180 or east>180 or south < -85 or north>85 or east-west>2 or north-south>2:
        raise ValueError('Координаты должны быть WGS84 [долгота, широта], участок — компактным.')
    geom = orient_polygons(geom)
    area = abs(Geod(ellps='WGS84').geometry_area_perimeter(geom)[0])/10000
    if not 0.05 <= area <= 20000:
        raise ValueError('Площадь участка должна быть от 0,05 до 20 000 га.')
    center = geom.representative_point()
    return {'geometry':mapping(geom),'area_ha':round(area,4),'latitude':center.y,'longitude':center.x}
