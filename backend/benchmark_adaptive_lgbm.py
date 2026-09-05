"""Transductive LightGBM: visible rows of target fields are training context."""
import argparse
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from source_model import baselines
from benchmark_sources import score
from benchmark_field_adaptation import selected_ids


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cache',required=True);parser.add_argument('--input',required=True)
    args=parser.parse_args();out=Path(args.cache);folds={};pooled={};truths=[]
    frame=pd.read_csv(args.input)
    ids=np.random.default_rng(20260905).permutation(sorted(frame.anon_polygon_id.unique()))
    for fold in range(4):
        holdout=np.array_split(ids,4)[fold]
        train=frame.loc[~frame.anon_polygon_id.isin(holdout)].reset_index(drop=True)
        test=frame.loc[frame.anon_polygon_id.isin(holdout)].reset_index(drop=True)
        eval_mask=test.primary_ndvi.between(-1,1).to_numpy() & (np.random.default_rng(9001+fold).random(len(test))<.15)
        visible=test.copy();visible.loc[eval_mask,'primary_ndvi']=np.nan
        pieces,(tx,ty,_)=joblib.load(out/f'features_{fold}.joblib')
        adaptive=joblib.load(out/f'adaptation_features_{fold}.joblib')
        x=pd.concat([p[0] for p in pieces+adaptive],ignore_index=True)
        y=np.concatenate([p[1] for p in pieces+adaptive])
        train_codes=np.concatenate(
            [selected_ids(train,seed) for seed in [142,243,344,445,546,647]]+
            [selected_ids(visible,seed) for seed in [771,882,993,1104,1215,1326]])
        x['field_code']=train_codes.astype('int32')
        tx=tx.copy();tx['field_code']=selected_ids(test,9001+fold).astype('int32')
        weights=np.r_[np.ones(sum(len(p[1]) for p in pieces)),np.full(sum(len(p[1]) for p in adaptive),4.)]
        linear,_=baselines(x);tl,_=baselines(tx)
        reference=joblib.load(out/f'fold_{fold}.joblib')['predictions']['expert_blend_0.5']
        model=LGBMRegressor(n_estimators=1600,num_leaves=63,learning_rate=.02,min_child_samples=30,
            reg_lambda=15,reg_alpha=.3,colsample_bytree=.85,subsample=.9,subsample_freq=1,n_jobs=2,
            random_state=52,verbosity=-1)
        model.fit(x,y-linear,sample_weight=weights,categorical_feature=['field_code'])
        direct=np.clip(tl+model.predict(tx),-1,1)
        predictions={'v15':reference,'adaptive_lgbm':direct}
        for weight in [.2,.35,.5,.65,.8]:predictions[f'blend_{weight}']=(1-weight)*reference+weight*direct
        folds[str(fold)]={k:score(ty,v) for k,v in predictions.items()};print(fold,json.dumps(folds[str(fold)]),flush=True)
        truths.append(ty)
        for name,pred in predictions.items():pooled.setdefault(name,[]).append(pred)
        joblib.dump({'truth':ty,'predictions':predictions},out/f'adaptive_lgbm_{fold}.joblib')
    aggregate={k:score(np.concatenate(truths),np.concatenate(v)) for k,v in pooled.items()}
    report={'folds':folds,'aggregate':aggregate};(out/'adaptive_lgbm_report.json').write_text(json.dumps(report,indent=2))
    print('AGGREGATE',json.dumps(aggregate),flush=True)
if __name__=='__main__':main()
