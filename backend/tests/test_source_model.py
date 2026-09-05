import numpy as np
import pandas as pd
import pytest
from reconstruction import build_features,masked
from source_model import extended_features


class FixedRegressor:
    feature_names_in_=np.array(['primary_ndvi_linear'])

    def __init__(self,value):self.value=value

    def predict(self,x):return np.full(len(x),self.value)


class FixedClassifier:
    def predict_proba(self,x):return np.tile([1.,0.,0.],(len(x),1))


def sample():
    return pd.DataFrame({
        'anon_polygon_id':['P']*4,
        'date':['2024-05-01','2024-05-03','2024-05-05','2024-05-07'],
        'primary_ndvi':[.2,.8,.4,.5],
        's2_ndvi':[.2,.8,.4,.5],
        'crop_type':['wheat']*4,
    })


def test_source_features_mask_all_hidden_measurements():
    frame=sample(); gap=np.array([False,True,False,False])
    clean=masked(frame,gap)
    before=extended_features(clean,build_features(clean))
    frame.loc[1,['primary_ndvi','s2_ndvi']]=[-.6,-.3]
    frame['ndvi_zscore']=999
    frame['ndvi_climatology_mean']=.99
    clean=masked(frame,gap)
    after=extended_features(clean,build_features(clean))
    pd.testing.assert_frame_equal(before,after)


def test_source_distances_are_days_and_missing_sensors_stay_missing():
    frame=masked(sample(),np.array([False,True,False,False]))
    feats=extended_features(frame,build_features(frame))
    assert feats.loc[1,'s2_ndvi_l_days']==pytest.approx(2.)
    assert feats.loc[1,'s2_ndvi_r_days']==pytest.approx(2.)
    assert feats.loc[1,'s2_ndvi_l_value']==pytest.approx(.2)
    assert feats.loc[1,'s2_ndvi_r_value']==pytest.approx(.4)
    assert pd.isna(feats.loc[1,'landsat_ndvi_l_value'])
    assert feats.loc[1,'landsat_ndvi_window_8_count']==0


def test_source_features_follow_input_row_order():
    frame=masked(sample(),np.array([False,True,False,False]))
    base=extended_features(frame,build_features(frame))
    order=[3,1,0,2]
    shuffled=frame.iloc[order].reset_index(drop=True)
    actual=extended_features(shuffled,build_features(shuffled))
    pd.testing.assert_frame_equal(actual,base.iloc[order].reset_index(drop=True))


def test_source_artifact_prediction_and_legacy_compatibility(tmp_path):
    import joblib
    from reconstruction import predict_frame
    frame=masked(sample(),np.array([False,True,False,False]))
    enriched=extended_features(frame,build_features(frame))
    artifact={'kind':'source_experts_v1','expertWeight':.5,'bundle':{
        'columns':list(enriched.columns),'general':FixedRegressor(.1),
        'classifier':FixedClassifier(),'experts':[FixedRegressor(.2) for _ in range(3)]}}
    path=tmp_path/'model.joblib';joblib.dump(artifact,path)
    assert predict_frame(frame,path)[1]==pytest.approx(.45)
    joblib.dump({'columns':['primary_ndvi_linear'],'model':FixedRegressor(.1),'weight':.5},path)
    assert predict_frame(frame,path)[1]==pytest.approx(.35)
