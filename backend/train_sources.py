"""Reproducible source-expert training; no ground-truth/test label files."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import sklearn
from reconstruction import build_features,masked,validate_frame
from source_model import extended_features,fit_bundle


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--benchmark',required=True)
    parser.add_argument('--expert-weight',type=float,default=.5)
    args=parser.parse_args()
    if not 0<=args.expert_weight<=1:parser.error('expert weight must be within [0,1]')
    frame=pd.read_csv(args.input);validate_frame(frame)
    benchmark=json.loads(Path(args.benchmark).read_text())
    if len(benchmark.get('folds',{}))!=4 or 'aggregate' not in benchmark:
        raise ValueError('Complete four-fold benchmark required before training release.')
    seeds=[142,243,344,445,546,647]
    features=[];targets=[];labels=[]
    for seed in seeds:
        mask=frame.primary_ndvi.between(-1,1).to_numpy() & (np.random.default_rng(seed).random(len(frame))<.15)
        clean=masked(frame,mask)
        features.append(extended_features(clean,build_features(clean)).loc[mask].reset_index(drop=True))
        original=frame.loc[mask]
        targets.append(original.primary_ndvi.to_numpy(float))
        labels.append(np.where(original.s2_ndvi.notna(),0,np.where(original.landsat_ndvi.notna(),1,2)))
        print('examples',seed,int(mask.sum()),flush=True)
    x=pd.concat(features,ignore_index=True);y=np.concatenate(targets);source=np.concatenate(labels)
    bundle=fit_bundle(x,y,source)
    provenance={'trainSha256':hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),'maskSeeds':seeds,'maskFraction':.15,
        'examples':len(y),'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,'sklearn':sklearn.__version__}
    artifact={'kind':'source_experts_v1','bundle':bundle,'expertWeight':args.expert_weight,'provenance':provenance}
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    joblib.dump(artifact,out/'gap_model.joblib')
    selected=f'expert_blend_{args.expert_weight}'
    # The UI's new-polygons section shows pooled squared errors across all folds.
    # Individual folds remain available in the downloadable benchmark report.
    splits={'new_polygons':{name:{**v,'gapScore':round(30*max(0,1-v['rmse']/.1),2)} for name,v in benchmark['aggregate'].items()}}
    report={'rows':len(frame),'observed':int(frame.primary_ndvi.between(-1,1).sum()),'polygons':int(frame.anon_polygon_id.nunique()),
        'maskedFraction':.15,'selectedWeight':args.expert_weight,'selectedMethod':selected,'splits':splits,
        'aggregate':benchmark['aggregate'],'validationFolds':benchmark['folds'],'evaluationNote':benchmark['validation'],
        'model':{'algorithm':'Temporal residual + satellite-source experts','trainingExamples':len(y)},'provenance':provenance}
    (out/'metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('TRAINED',json.dumps(provenance),flush=True)


if __name__=='__main__':main()
