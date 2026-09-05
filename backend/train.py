"""Обучение на нескольких масках, повторяющих долю скрытых строк test dataset."""
import argparse
import json
import time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from reconstruction import build_features, masked, validate_frame


def scores(truth,pred):
    rmse = float(np.sqrt(np.mean((truth-pred)**2)))
    return {'rmse':rmse,'mae':float(np.mean(np.abs(truth-pred))),'gapScore':round(30*max(0,1-rmse/0.10),2),'n':len(truth)}


def train(path, output):
    frame = pd.read_csv(path)
    validate_frame(frame)
    known = frame.primary_ndvi.notna().to_numpy() & frame.primary_ndvi.between(-1,1).to_numpy()
    seeds = [142,243,344,445,546,647]
    datasets = []
    for seed in seeds:
        mask = known & (np.random.default_rng(seed).random(len(frame))<0.15)
        feats = build_features(masked(frame,mask)).loc[mask].reset_index(drop=True)
        target = frame.loc[mask,'primary_ndvi'].to_numpy()
        keys = frame.loc[mask,['anon_polygon_id','date']].reset_index(drop=True)
        linear = np.nan_to_num(feats.primary_ndvi_linear.to_numpy(),nan=.35)
        datasets.append((feats,target,keys,linear))
        print('features',seed,len(target),flush=True)
    feats,target,keys,linear = datasets[0]
    mean = np.nan_to_num(feats.primary_ndvi_mean.to_numpy(),nan=.35)
    pchip = np.nan_to_num(feats.primary_ndvi_pchip.to_numpy(),nan=.35)
    unseen = sorted(frame.anon_polygon_id.unique())[-8:]
    splits = {'new_polygons':keys.anon_polygon_id.isin(unseen).to_numpy(), 'new_season':keys.date.str.startswith('2024').to_numpy()}
    report = {'seeds':seeds,'maskedFraction':.15,'rows':len(frame),'observed':int(known.sum()),'polygons':int(frame.anon_polygon_id.nunique()),'splits':{}}
    weights = [0.,.25,.5,.75,1.]
    total_errors = {w:[] for w in weights}
    for name,test in splits.items():
        train_x=[]; train_y=[]
        for part_x,part_target,part_keys,part_linear in datasets:
            if name=='new_polygons':
                keep=~part_keys.anon_polygon_id.isin(unseen).to_numpy()
            else:
                keep=~part_keys.date.str.startswith('2024').to_numpy()
            train_x.append(part_x.loc[keep])
            train_y.append((part_target-part_linear)[keep])
        model = HistGradientBoostingRegressor(max_iter=500,max_leaf_nodes=31,l2_regularization=20,learning_rate=.035,random_state=42)
        model.fit(pd.concat(train_x,ignore_index=True),np.concatenate(train_y))
        correction = model.predict(feats.loc[test])
        variants = {'nearest_mean':scores(target[test],mean[test]), 'linear':scores(target[test],linear[test]), 'pchip':scores(target[test],pchip[test])}
        for weight in weights:
            pred = np.clip(linear[test]+weight*correction,-1,1)
            variants['residual_'+str(weight)] = scores(target[test],pred)
            total_errors[weight].extend((target[test]-pred)**2)
        report['splits'][name] = variants
        print(name,json.dumps(variants),flush=True)
    weight = min(weights,key=lambda w:np.mean(total_errors[w]))
    # Финальный артефакт обучается на нескольких независимых масках reference train.
    all_x=pd.concat([part[0] for part in datasets],ignore_index=True)
    all_y=np.concatenate([part[1]-part[3] for part in datasets])
    model = HistGradientBoostingRegressor(max_iter=500,max_leaf_nodes=31,l2_regularization=20,learning_rate=.035,random_state=42)
    model.fit(all_x,all_y)
    output = Path(output)
    output.mkdir(parents=True,exist_ok=True)
    joblib.dump({'model':model,'columns':list(all_x.columns),'weight':weight,'seeds':seeds},output/'gap_model.joblib')
    report['selectedWeight'] = weight
    report['evaluationNote'] = 'Метрики на искусственных пропусках reference train, не скрытая метрика организаторов. Вес выбран по этим validation splits.'
    report['model'] = {'algorithm':'Multi-mask HistGradientBoosting residual + linear + crop and orbit features','max_iter':500,'max_leaf_nodes':31,'l2_regularization':20,'learning_rate':.035,'trainingExamples':len(all_y)}
    (output/'metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('selected_weight',weight,flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',required=True)
    parser.add_argument('--output',default='backend/models')
    args = parser.parse_args()
    train(args.input,args.output)
