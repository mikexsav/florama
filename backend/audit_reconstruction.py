"""Error attribution on held-out training rows, never private labels."""
import argparse
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cache',required=True)
    args=parser.parse_args();out=Path(args.cache);parts=[]
    for fold in range(4):
        _,(x,y,source)=joblib.load(out/f'features_{fold}.joblib')
        p=joblib.load(out/f'fold_{fold}.joblib')['predictions']['expert_blend_0.5']
        d=pd.DataFrame({'truth':y,'prediction':p,'source':source,'fold':fold})
        distance=np.stack([np.minimum(x[f'{s}_l_days'].fillna(999),x[f'{s}_r_days'].fillna(999)) for s in ['s2_ndvi','landsat_ndvi','modis_ndvi']],axis=1)
        d['distance']=distance[np.arange(len(y)),source]
        d['distance_bin']=pd.cut(d.distance,[-1,3,8,16,32,1000],labels=['0-3','3-8','8-16','16-32','32+'])
        d['squared_error']=(y-p)**2;parts.append(d)
    frame=pd.concat(parts,ignore_index=True)
    def summarize(g):
        return {'n':len(g),'rmse':float(np.sqrt(g.squared_error.mean())), 'bias':float((g.prediction-g.truth).mean()),'errorShare':float(g.squared_error.sum()/frame.squared_error.sum())}
    report={'overall':summarize(frame),'source':{str(k):summarize(g) for k,g in frame.groupby('source')},'distance':{str(k):summarize(g) for k,g in frame.groupby('distance_bin',observed=True)}}
    ordered=frame.sort_values('squared_error',ascending=False)
    report['top10PercentErrorShare']=float(ordered.head(int(len(frame)*.1)).squared_error.sum()/frame.squared_error.sum())
    (out/'error_audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)


if __name__=='__main__':main()
