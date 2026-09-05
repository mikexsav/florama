"""Реальные COG-каналы Sentinel-2, общий 20-метровый грид и SCL-маска."""
import math
from urllib.parse import urlparse
import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from pyproj import Transformer
from shapely.geometry import shape, mapping, box
from shapely.ops import transform as transform_shape
from scipy.ndimage import label, center_of_mass

BANDS = ['blue','red','nir','nir08','rededge1','swir16','swir22','scl']


def ratio(a,b):
    return np.divide(a-b,a+b,out=np.full_like(a,np.nan),where=np.abs(a+b)>1e-6)


def indices(bands):
    blue,red,nir,rededge,swir = [bands[k] for k in ['blue','red','nir','rededge1','swir16']]
    denom=nir+6*red-7.5*blue+1
    evi=np.divide(2.5*(nir-red),denom,out=np.full_like(nir,np.nan),where=np.abs(denom)>1e-6)
    return {'ndvi':ratio(nir,red),'ndmi':ratio(nir,swir),'ndre':ratio(bands['nir08'],rededge),'bsi':ratio(swir+red,nir+blue),'evi':evi,'swir_ratio':np.divide(swir,bands['swir22'],out=np.full_like(nir,np.nan),where=bands['swir22']>1e-6)}


def trusted_href(asset):
    url=asset['href']
    parsed=urlparse(url)
    if parsed.scheme!='https' or not (parsed.hostname or '').endswith('.amazonaws.com'):
        raise ValueError('Неподдерживаемый адрес спутникового ресурса.')
    return url


def reflectance(raw, asset, properties):
    meta=asset.get('raster:bands',[{}])[0]
    offset=meta.get('offset',0.)
    # Часть COG уже приведена к BOA: повторное вычитание 1000 DN портит сигнал.
    # У некоторых объектов каталога asset offset противоречит явному флагу конвертера.
    if properties.get('earthsearch:boa_offset_applied') is True:
        offset=0.
    return raw*meta.get('scale',.0001)+offset


def analyze_scene(item,geometry,include_grid=False):
    geom=shape(geometry)
    assets=item['assets']
    bands={}
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',GDAL_HTTP_TIMEOUT='20',GDAL_HTTP_MAX_RETRY='1',GDAL_HTTP_RETRY_DELAY='1',VSI_CACHE=True):
        with rasterio.open(trusted_href(assets['red'])) as src:
            crs=src.crs
        project=Transformer.from_crs('EPSG:4326',crs,always_xy=True).transform
        unproject=Transformer.from_crs(crs,'EPSG:4326',always_xy=True).transform
        projected=transform_shape(project,geom)
        west,south,east,north=projected.bounds
        resolution=max(20,math.ceil(math.sqrt((east-west)*(north-south)/65536)/20)*20)
        width=max(1,math.ceil((east-west)/resolution)); height=max(1,math.ceil((north-south)/resolution))
        grid=from_origin(west,north,resolution,resolution)
        inside=geometry_mask([mapping(projected)],out_shape=(height,width),transform=grid,invert=True)
        valid=inside.copy()
        for name in BANDS:
            asset=assets[name]
            with rasterio.open(trusted_href(asset)) as source:
                with WarpedVRT(source,crs=crs,transform=grid,width=width,height=height,resampling=Resampling.nearest if name=='scl' else Resampling.bilinear) as vrt:
                    raw=vrt.read(1,masked=True)
            valid &= ~np.ma.getmaskarray(raw)
            values=raw.filled(0).astype('float32')
            if name!='scl':
                values=reflectance(values,asset,item['properties'])
                valid &= values>=0
            bands[name]=values
        valid &= np.isin(bands['scl'],[4,5,6])
        values=indices(bands)
        valid &= np.isfinite(values['ndvi']) & (np.abs(values['ndvi'])<=1)
        fraction=float(valid.sum()/max(1,inside.sum()))
        result={'date':item['properties']['datetime'][:10],'datetime':item['properties']['datetime'],'sceneId':item['id'],'source':'ESA Sentinel-2 L2A / Earth Search','tileCloudPercent':item['properties'].get('eo:cloud_cover'),'validFraction':round(fraction,4),'resolutionM':resolution,'validPixels':int(valid.sum()),'usable':fraction>=.25 and int(valid.sum())>=3}
        for key,value in values.items():
            eligible=valid & np.isfinite(value)
            result[key]=round(float(np.median(value[eligible])),5) if result['usable'] and eligible.any() else None
        if not result['usable'] or not include_grid:
            return result
        vegetation=valid & (values['ndvi']>.2)
        weak=vegetation & (values['ndvi']<max(.3,float(np.median(values['ndvi'][valid]))-.15)) & (values['ndmi']<.1)
        components,count=label(weak)
        zones=[]
        for n in range(1,count+1):
            count_pixels=int((components==n).sum())
            if count_pixels<3:
                continue
            row,col=center_of_mass(weak,components,n)
            lon,lat=unproject(west+(col+.5)*resolution,north-(row+.5)*resolution)
            zones.append({'lat':lat,'lon':lon,'areaHa':round(count_pixels*resolution**2/10000,3),'reason':'Совместное локальное снижение NDVI и NDMI; нужен осмотр, болезнь не подтверждена.'})
        result['inspectionPoints']=sorted(zones,key=lambda x:-x['areaHa'])[:5]
        result['stressAreaHa']=round(int(weak.sum())*resolution**2/10000,3)
        result['vegetationFraction']=round(float(vegetation.sum()/max(1,valid.sum())),3)
        result['bareSoilFraction']=round(float((valid & (bands['scl']==5)).sum()/max(1,valid.sum())),3)
        stride=max(1,math.ceil(math.sqrt(width*height/600)))
        cells=[]
        for row in range(0,height,stride):
            for col in range(0,width,stride):
                block=np.s_[row:min(row+stride,height),col:min(col+stride,width)]
                good=valid[block]
                if not good.any():
                    continue
                cell=box(west+col*resolution,north-min(row+stride,height)*resolution,west+min(col+stride,width)*resolution,north-row*resolution).intersection(projected)
                if cell.is_empty:
                    continue
                props={k:round(float(np.median(v[block][good & np.isfinite(v[block])])),4) if (good & np.isfinite(v[block])).any() else None for k,v in values.items()}
                rgb=[int(np.clip(np.median(bands[k][block][good])*2.5,0,1)*255) for k in ['nir','red','blue']]
                props['falseColor']='#'+''.join(f'{v:02x}' for v in rgb)
                cells.append({'type':'Feature','geometry':mapping(transform_shape(unproject,cell)),'properties':props})
        result['grid']={'type':'FeatureCollection','features':cells}
        result['mapCellSizeM']=resolution*stride
        return result
