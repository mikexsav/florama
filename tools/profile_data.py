import json
import zipfile
from pathlib import Path
import pandas as pd

root = Path('data/raw')
root.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile('E:/doc-1788536686.zip') as archive:
    archive.extract('train_dataset.csv', root)
for name, path in [('train', root / 'train_dataset.csv'), ('private', Path('E:/doc-1788536731.csv'))]:
    df = pd.read_csv(path)
    print(name, df.shape, list(df.columns))
    print('polygons', df.anon_polygon_id.nunique(), 'range', df.date.min(), df.date.max())
    print('nonnull', df.count().to_dict())
    print('gaps', df.is_synthetic_gap.value_counts().to_dict() if 'is_synthetic_gap' in df else 'absent')
    print('years', df.date.str[:4].value_counts().sort_index().to_dict())
    print('first known', df[df.primary_ndvi.notna()].head(3).to_json(orient='records',force_ascii=False))
