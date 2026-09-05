"""Choose convex v15/v16/LightGBM weights on pooled out-of-fold errors."""
import argparse,json
from pathlib import Path
import joblib,numpy as np,pandas as pd


def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',required=True);p.add_argument('--v15');p.add_argument('--v16');p.add_argument('--lgbm');p.add_argument('--output')
    a=p.parse_args();cache=Path(a.cache);ys=[];ps=[[],[],[]]
    for fold in range(4):
        f=joblib.load(cache/f'field_adaptation_{fold}.joblib');l=joblib.load(cache/f'adaptive_lgbm_{fold}.joblib')
        ys.append(f['truth']);ps[0].append(f['predictions']['v15']);ps[1].append(f['predictions']['mixed']);ps[2].append(l['predictions']['adaptive_lgbm'])
    y=np.concatenate(ys);pred=[np.concatenate(v) for v in ps];best=None
    for w16 in np.arange(0,1.001,.05):
        for wl in np.arange(0,1.001-w16,.05):
            w15=1-w16-wl;p=w15*pred[0]+w16*pred[1]+wl*pred[2];rmse=float(np.sqrt(np.mean((y-p)**2)))
            if best is None or rmse<best['rmse']:best={'rmse':rmse,'weights':[float(w15),float(w16),float(wl)]}
    print(json.dumps(best),flush=True)
    if not all([a.v15,a.v16,a.lgbm,a.output]):return
    frames=[pd.read_csv(x) for x in [a.v15,a.v16,a.lgbm]];keys=frames[0][['anon_polygon_id','date']]
    for frame in frames:
        if not frame[['anon_polygon_id','date']].equals(keys):raise ValueError('Submission keys/order differ')
    values=sum(weight*frame.primary_ndvi_true.to_numpy() for weight,frame in zip(best['weights'],frames))
    result=keys.copy();result['primary_ndvi_true']=np.clip(values,-1,1);result.to_csv(a.output,index=False)


if __name__=='__main__':main()
