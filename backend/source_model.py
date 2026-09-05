"""Source-aware reconstruction using only visible observations at inference."""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

SENSORS = ('s2_ndvi', 'landsat_ndvi', 'modis_ndvi')


def extended_features(frame, base):
    frame = frame.reset_index(drop=True)
    result = base.copy()
    dates = pd.to_datetime(frame.date)
    extra = pd.DataFrame(index=frame.index, dtype=float)
    for _, group in frame.assign(_year=dates.dt.year).groupby(['anon_polygon_id', '_year'], sort=False):
        ids = group.index
        # Explicit unit prevents a pandas datetime64[us]/[ns] scale mismatch.
        x = (pd.to_datetime(group.date) - pd.Timestamp('2000-01-01')).dt.total_seconds().to_numpy()/86400
        local = {}
        for sensor in SENSORS:
            values = pd.to_numeric(group.get(sensor, pd.Series(np.nan, index=ids)), errors='coerce').to_numpy(float)
            good = np.isfinite(values) & (np.abs(values) <= 1)
            xx, yy = x[good], values[good]
            order = np.argsort(xx)
            xx, yy = xx[order], yy[order]
            for period in ([5,10] if sensor=='s2_ndvi' else [8,16] if sensor=='landsat_ndvi' else [16]):
                phase = np.mod(x, period).astype(int)
                counts = np.bincount(np.mod(xx, period).astype(int), minlength=period)
                local[f'{sensor}_orbit_{period}'] = counts[phase]/max(len(xx),1)
            at = np.searchsorted(xx, x)
            for side, offset in [('l',-1),('r',0),('l2',-2),('r2',1),('l3',-3),('r3',2)]:
                position = at + offset
                valid = (position >= 0) & (position < len(xx))
                if len(xx):
                    pos = np.clip(position,0,len(xx)-1)
                    local[f'{sensor}_{side}_days'] = np.where(valid, np.abs(x-xx[pos]), np.nan)
                    local[f'{sensor}_{side}_value'] = np.where(valid, yy[pos], np.nan)
                else:
                    local[f'{sensor}_{side}_days'] = np.full(len(x),np.nan)
                    local[f'{sensor}_{side}_value'] = np.full(len(x),np.nan)
            for window in [8,24,48]:
                lo=np.searchsorted(xx,x-window)
                hi=np.searchsorted(xx,x+window,side='right')
                counts=hi-lo
                sums=np.r_[0,np.cumsum(yy)]
                squares=np.r_[0,np.cumsum(yy*yy)]
                avg=(sums[hi]-sums[lo])/np.maximum(counts,1)
                variance=np.maximum((squares[hi]-squares[lo])/np.maximum(counts,1)-avg*avg,0)
                local[f'{sensor}_window_{window}_mean']=np.where(counts,avg,np.nan)
                local[f'{sensor}_window_{window}_std']=np.where(counts,np.sqrt(variance),np.nan)
                local[f'{sensor}_window_{window}_count']=counts
            # Local cross-sensor offset is estimated from simultaneous visible rows.
            for other in SENSORS:
                if other==sensor:
                    continue
                ov=pd.to_numeric(group.get(other,pd.Series(np.nan,index=ids)),errors='coerce').to_numpy(float)
                overlap=good & np.isfinite(ov) & (np.abs(ov)<=1)
                diff=values[overlap]-ov[overlap]
                local[f'{sensor}_minus_{other}']=np.full(len(x),np.median(diff) if len(diff)>=3 else np.nan)
        piece=pd.DataFrame(local,index=ids)
        extra=extra.reindex(columns=piece.columns)
        extra.loc[ids]=piece
    return pd.concat([result,extra],axis=1).replace([np.inf,-np.inf],np.nan)


def baselines(features):
    linear=features.primary_ndvi_linear.fillna(.35).to_numpy(float)
    sensors=np.stack([features[f'{s}_linear'].fillna(pd.Series(linear,index=features.index)).to_numpy(float) for s in SENSORS],axis=1)
    return linear,sensors


def fit_bundle(features, target, labels, seed=42, experts=True, sample_weight=None, categorical_features='from_dtype'):
    linear,candidates=baselines(features)
    general=HistGradientBoostingRegressor(max_iter=600,max_leaf_nodes=31,l2_regularization=20,learning_rate=.035,early_stopping=False,random_state=seed,categorical_features=categorical_features)
    general.fit(features,target-linear,sample_weight=sample_weight)
    bundle={'columns':list(features.columns),'general':general,'experts':[]}
    if experts:
        classifier=HistGradientBoostingClassifier(max_iter=300,max_leaf_nodes=15,l2_regularization=12,learning_rate=.045,early_stopping=False,random_state=seed,categorical_features=categorical_features)
        classifier.fit(features,labels,sample_weight=sample_weight)
        bundle['classifier']=classifier
        for source in range(3):
            keep=labels==source
            model=HistGradientBoostingRegressor(max_iter=500,max_leaf_nodes=23,l2_regularization=18,learning_rate=.035,early_stopping=False,random_state=seed+source,categorical_features=categorical_features)
            source_x=features.loc[keep]
            # Some bands never occur in a source subset. Remove empty/constant
            # columns using only training rows (also avoids empty-bin failures).
            useful=source_x.nunique(dropna=True)>1
            weights=None if sample_weight is None else sample_weight[keep]
            model.fit(source_x.loc[:,useful],(target-candidates[:,source])[keep],sample_weight=weights)
            bundle['experts'].append(model)
    return bundle


def predict_bundle(bundle, features):
    x=features[bundle['columns']]
    linear,candidates=baselines(x)
    general=np.clip(linear+bundle['general'].predict(x),-1,1)
    if not bundle['experts']:
        return general,general
    probabilities=bundle['classifier'].predict_proba(x)
    predictions=np.stack([np.clip(candidates[:,i]+model.predict(x[list(model.feature_names_in_)]),-1,1) for i,model in enumerate(bundle['experts'])],axis=1)
    return general,np.sum(probabilities*predictions,axis=1)
