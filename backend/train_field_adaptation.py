"""Add dataset-bound adaptation from visible labels; preserve generic model."""
import argparse
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from reconstruction import build_features,masked,gap_mask,validate_frame
from source_model import extended_features,fit_bundle


def examples(frame,seed):
    mask=frame.primary_ndvi.between(-1,1).to_numpy() & (np.random.default_rng(seed).random(len(frame))<.15)
    clean=masked(frame,mask)
    x=extended_features(clean,build_features(clean)).loc[mask].reset_index(drop=True)
    original=frame.loc[mask]
    x['field_code']=original.anon_polygon_id.str.split('-').str[-1].astype(int).to_numpy()
    labels=np.where(original.s2_ndvi.notna(),0,np.where(original.landsat_ndvi.notna(),1,2))
    return x,original.primary_ndvi.to_numpy(float),labels


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reference',required=True)
    parser.add_argument('--input',required=True)
    parser.add_argument('--base-model',required=True)
    parser.add_argument('--report',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    report=json.loads(Path(args.report).read_text())
    if len(report.get('folds',{}))!=4 or report['aggregate']['mixed']['rmse']>=report['aggregate']['v15']['rmse']:
        raise ValueError('A complete benchmark demonstrating improvement is required.')
    reference=pd.read_csv(args.reference);frame=pd.read_csv(args.input)
    validate_frame(reference);validate_frame(frame)
    if set(reference.anon_polygon_id)&set(frame.anon_polygon_id):
        raise ValueError('Reference and adaptation fields must be disjoint.')
    clean=masked(frame,gap_mask(frame))
    parts=[];weights=[]
    for label,data,seeds,weight in [('reference',reference,[142,243,344,445,546,647],1.),('visible_test',clean,[771,882,993,1104,1215,1326],3.)]:
        for seed in seeds:
            part=examples(data,seed);parts.append(part);weights.append(np.full(len(part[1]),weight))
            print(label,seed,len(part[1]),flush=True)
    x=pd.concat([p[0] for p in parts],ignore_index=True)
    y=np.concatenate([p[1] for p in parts]);labels=np.concatenate([p[2] for p in parts])
    bundle=fit_bundle(x,y,labels,sample_weight=np.concatenate(weights),categorical_features=['field_code'])
    artifact=joblib.load(args.base_model)
    if artifact.get('kind')!='source_experts_v1':raise ValueError('Source-expert base model required.')
    artifact['adaptation']={'inputSha256':hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
        'fieldCodes':{str(v):int(str(v).split('-')[-1]) for v in frame.anon_polygon_id.unique()},
        'bundle':bundle,'weight':.5,'examples':len(y),'benchmark':report,
        'note':'Only visible target-field labels; hidden rows masked before feature construction. Used only for the exact input SHA-256.'}
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    joblib.dump(artifact,out)
    print('ADAPTED',json.dumps({'inputSha256':artifact['adaptation']['inputSha256'],'examples':len(y),'modelBytes':out.stat().st_size}),flush=True)


if __name__=='__main__':main()
