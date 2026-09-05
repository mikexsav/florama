"""Восстановление рядов: временные соседи и модель поправки к интерполяции.

Запрещённые признаки ndvi_zscore/status и готовая климатология не используются.
При валидации вся динамика скрытой строки маскируется ДО построения признаков.
"""
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

DYNAMIC = ['primary_ndvi','s2_ndvi','s2_evi','s2_ndwi','landsat_ndvi','landsat_evi',
           'landsat_ndwi','modis_ndvi','modis_evi','era5_temp_c','era5_precip_mm',
           'ndvi_climatology_mean','ndvi_climatology_std','n_reference_years','ndvi_zscore','status']


def validate_frame(frame):
    required = {'anon_polygon_id', 'date', 'primary_ndvi'}
    if not required.issubset(frame.columns) or frame.empty:
        raise ValueError('CSV должен содержать anon_polygon_id,date,primary_ndvi и строки данных.')
    if frame[['anon_polygon_id','date']].isna().any().any() or frame.duplicated(['anon_polygon_id','date']).any():
        raise ValueError('Пустые или повторяющиеся ключи полигон+дата.')
    pd.to_datetime(frame.date, format='%Y-%m-%d', errors='raise')
    values = pd.to_numeric(frame.primary_ndvi, errors='raise').dropna()
    if not np.isfinite(values).all():
        raise ValueError('NDVI не должен содержать бесконечности.')


def gap_mask(frame):
    if 'is_synthetic_gap' not in frame:
        raise ValueError('Нет обязательного поля is_synthetic_gap.')
    values = frame.is_synthetic_gap.astype(str).str.lower()
    if not values.isin(['true','false']).all():
        raise ValueError('is_synthetic_gap должен быть True или False.')
    return values.eq('true').to_numpy()


def masked(frame, mask):
    result = frame.copy()
    for col in DYNAMIC:
        if col in result:
            result[col] = result[col].where(~mask)
    return result


def neighbors(x, y, name, features):
    good = np.isfinite(y)
    xx, yy = x[good], y[good]
    if not len(xx):
        for suffix in ['linear','mean','left','right','dl','dr','pchip','l2','r2','l3','r3']:
            features[name+'_'+suffix] = np.full(len(x), np.nan)
        return
    at = np.searchsorted(xx, x, side='left')
    left, right = np.clip(at-1,0,len(xx)-1), np.clip(at,0,len(xx)-1)
    dl, dr = x-xx[left], xx[right]-x
    features[name+'_linear'] = np.interp(x, xx, yy)
    features[name+'_mean'] = (yy[left]+yy[right])/2
    features[name+'_left'], features[name+'_right'] = yy[left], yy[right]
    features[name+'_dl'], features[name+'_dr'] = dl, dr
    if len(xx) > 2:
        pc = PchipInterpolator(xx, yy, extrapolate=False)(x)
        features[name+'_pchip'] = np.where(np.isfinite(pc),pc,features[name+'_linear'])
    else:
        features[name+'_pchip'] = features[name+'_linear']
    for k in [2,3]:
        features[name+'_l'+str(k)] = yy[np.clip(at-k,0,len(xx)-1)]
        features[name+'_r'+str(k)] = yy[np.clip(at+k-1,0,len(xx)-1)]


def build_features(frame):
    frame = frame.reset_index(drop=True)
    dt = pd.to_datetime(frame.date)
    parts = []
    # Не соединяем октябрь одного сезона с апрелем следующего.
    for _, group in frame.assign(_year=dt.dt.year).groupby(['anon_polygon_id','_year'], sort=False):
        group = group.sort_values('date')
        dates = pd.to_datetime(group.date)
        x = dates.astype('int64').to_numpy()/86400000000000
        doy = dates.dt.dayofyear.to_numpy()
        feat = {'doy':doy, 'year':dates.dt.year.to_numpy(), 'sin':np.sin(2*np.pi*doy/365.25), 'cos':np.cos(2*np.pi*doy/365.25)}
        crops = group.get('crop_type', pd.Series('',index=group.index)).fillna('').astype(str)
        feat['crop'] = np.array([int(hashlib.sha256(v.encode()).hexdigest()[:6],16)%10000 for v in crops])
        # Категория культуры нужна модели как отдельный признак, а не как случайный порядок чисел.
        # Хеш-слоты стабильны между train и новым CSV и не раскрывают идентификаторы участков.
        crop_slots=np.array([int(hashlib.sha256(v.encode()).hexdigest()[:8],16)%16 for v in crops])
        for slot in range(16):
            feat['crop_bucket_'+str(slot)]=(crop_slots==slot).astype(float)
        for col in DYNAMIC[:11]:
            y = pd.to_numeric(group.get(col,pd.Series(np.nan,index=group.index)), errors='coerce').to_numpy(dtype=float)
            if 'ndvi' in col:
                y = np.where(np.abs(y)<=1,y,np.nan)
            neighbors(x,y,col,feat)
        parts.append(pd.DataFrame(feat,index=group.index))
    result = pd.concat(parts).sort_index().replace([np.inf,-np.inf],np.nan)
    # Соседние AOI выбираются по корреляции ВИДИМЫХ наблюдений, не по скрытым меткам.
    # Это трансдуктивная интерполяция: пригодные наблюдения других полей доступны и при инференсе.
    panel = frame.pivot(index='date',columns='anon_polygon_id',values='primary_ndvi')
    panel = panel.where(panel.abs()<=1)
    peer_cols = ['peer_mean','peer_median','peer_std','peer_count','peer_corr','peer_best']
    for col in peer_cols:
        result[col] = np.nan
    if len(panel.columns)>1:
        corr = panel.corr(min_periods=25)
        for polygon, group in frame.groupby('anon_polygon_id',sort=False):
            candidates=corr[polygon].drop(index=polygon).dropna().sort_values(ascending=False).head(5)
            candidates=candidates[candidates>.45]
            estimates=[]; quality=[]
            for other,r in candidates.items():
                pair=panel[[polygon,other]].dropna()
                if len(pair)<25:
                    continue
                xx=pair[other].to_numpy(); yy=pair[polygon].to_numpy()
                slope=np.cov(xx,yy)[0,1]/max(np.var(xx,ddof=1),1e-6)
                offset=float(np.mean(yy)-slope*np.mean(xx))
                estimates.append(panel[other].reindex(group.date).to_numpy()*slope+offset)
                quality.append(float(r))
            if estimates:
                predictions=np.stack(estimates,axis=1)
                count=np.isfinite(predictions).sum(axis=1)
                weights=np.where(np.isfinite(predictions),np.array(quality)[None,:]**2,0.)
                avg=np.nansum(predictions*weights,axis=1)/np.maximum(weights.sum(axis=1),1e-6)
                result.loc[group.index,'peer_mean']=np.where(count,avg,np.nan)
                # pandas корректно оставляет NaN при полном отсутствии одновременных наблюдений.
                peer=pd.DataFrame(predictions)
                result.loc[group.index,'peer_median']=peer.median(axis=1).to_numpy()
                result.loc[group.index,'peer_std']=peer.std(axis=1).to_numpy()
                result.loc[group.index,'peer_count']=count
                result.loc[group.index,'peer_corr']=max(quality)
                result.loc[group.index,'peer_best']=peer.bfill(axis=1).iloc[:,0].to_numpy()
    return result


def predict_frame(frame, model_path=None, method='ensemble'):
    validate_frame(frame)
    feats = build_features(frame)
    linear = feats.primary_ndvi_linear.to_numpy()
    linear = np.nan_to_num(linear, nan=0.35)
    if method == 'linear':
        return np.clip(linear,-1,1)
    path = Path(model_path or Path(__file__).parent/'models'/'gap_model.joblib')
    if path.exists():
        import joblib
        artifact = joblib.load(path)
        correction = artifact['model'].predict(feats[artifact['columns']])
        weight = artifact.get('weight',1.)
        return np.clip(linear + weight*correction, -1,1)
    # Явный воспроизводимый fallback, без фиктивного результата ML.
    return np.clip(linear,-1,1)


def submission(input_path, output_path, model_path=None):
    frame = pd.read_csv(input_path)
    validate_frame(frame)
    mask = gap_mask(frame)
    if not mask.any():
        raise ValueError('В файле нет контрольных пропусков.')
    clean = masked(frame,mask)
    pred = predict_frame(clean,model_path)[mask]
    out = frame.loc[mask,['anon_polygon_id','date']].copy()
    # Внешний валидатор принимает целевую колонку под этим именем.
    # Значения по-прежнему являются восстановленными оценками модели.
    out['primary_ndvi_true'] = pred
    if not np.isfinite(pred).all() or len(out) != int(mask.sum()):
        raise ValueError('Не все контрольные точки восстановлены.')
    Path(output_path).parent.mkdir(parents=True,exist_ok=True)
    out.to_csv(output_path,index=False,float_format='%.8f',encoding='utf-8')
    return {'rows':len(out),'polygons':int(out.anon_polygon_id.nunique()),'columns':list(out.columns)}
