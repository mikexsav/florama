"""Интерпретируемые аномалии: наблюдения отделены от реконструкции и гипотез."""
import math
from datetime import date, timedelta
import numpy as np
import pandas as pd
from reconstruction import predict_frame


def finite(value):
    return isinstance(value,(int,float,np.number)) and math.isfinite(float(value))


def build_analysis(observations, history, weather, start, end, restore=True, detect=True):
    dates=pd.date_range(start,end)
    observed={r['date']:r for r in observations if r.get('usable') and finite(r.get('ndvi'))}
    meteo={r['date']:r for r in weather}
    frame=pd.DataFrame({'anon_polygon_id':'live','date':dates.strftime('%Y-%m-%d'),'primary_ndvi':[observed.get(str(d.date()),{}).get('ndvi',np.nan) for d in dates]})
    for col,key in [('s2_ndvi','ndvi'),('s2_evi','evi'),('s2_ndwi','ndmi')]:
        frame[col]=[observed.get(str(d.date()),{}).get(key,np.nan) for d in dates]
    frame['era5_temp_c']=[meteo.get(str(d.date()),{}).get('temperature_2m_mean',np.nan) for d in dates]
    frame['era5_precip_mm']=[meteo.get(str(d.date()),{}).get('precipitation_sum',np.nan) for d in dates]
    prediction=predict_frame(frame) if len(observed)>=2 and restore else None
    known_days=[date.fromisoformat(day).toordinal() for day in observed]
    series=[]
    for i,day in enumerate(dates):
        key=str(day.date()); raw=observed.get(key)
        distance=min((abs(day.date().toordinal()-v) for v in known_days),default=999)
        # Не рисуем уверенную непрерывность через месяцы без единого снимка.
        restored=float(prediction[i]) if prediction is not None and distance<=30 else None
        value=raw['ndvi'] if raw else restored
        candidates=[r for r in history if finite(r.get('ndvi')) and abs(date.fromisoformat(r['date']).timetuple().tm_yday-day.dayofyear)<=22]
        years=len({r['date'][:4] for r in candidates})
        norm=float(np.median([r['ndvi'] for r in candidates])) if years>=2 and len(candidates)>=3 else None
        std=max(.04,float(np.std([r['ndvi'] for r in candidates]))) if norm is not None else None
        z=(value-norm)/std if value is not None and norm is not None else None
        status='unknown' if z is None else 'critical' if z < -2 else 'warning' if z < -1 else 'normal'
        series.append({'date':key,'observed':raw['ndvi'] if raw else None,'reconstructed':restored if not raw else None,'ndvi':value,'normal':norm,'normalStd':std,'referenceYears':years,'z':z,'status':status,'nearestObservationDays':distance if known_days else None,'confidence':'observed' if raw else 'low' if distance>10 else 'estimated','temperature':meteo.get(key,{}).get('temperature_2m_mean'),'precipitation':meteo.get(key,{}).get('precipitation_sum')})
    events=[]
    active=[]
    def finish():
        nonlocal active
        if not active:
            return
        real=[x for x in active if x['observed'] is not None]
        # Интерполированный участок без подтверждающего снимка — не детекция.
        if real and (len(active)>=3 or min(x['z'] for x in real)<-2):
            first,last=active[0]['date'],active[-1]['date']
            context=[r for r in weather if str(date.fromisoformat(first)-timedelta(days=14))<=r['date']<=last]
            temps=[r.get('temperature_2m_max') for r in context if finite(r.get('temperature_2m_max'))]
            rain=[r.get('precipitation_sum') for r in context if finite(r.get('precipitation_sum'))]
            hints=[]
            if temps and max(temps)>32:
                hints.append('Высокая температура совпадает со снижением: возможен тепловой стресс.')
            if len(rain)>=10 and sum(rain)<10:
                hints.append('Мало осадков за предшествующие дни: возможен дефицит влаги.')
            if not hints:
                hints.append('Причина не установлена: проверьте фазу культуры, уборку, вредителей и качество снимков.')
            events.append({'start':first,'end':last,'days':len(active),'minZ':round(min(x['z'] for x in active),3),'severity':'critical' if min(x['z'] for x in active)<-2 else 'warning','observedSupport':len(real),'explanation':' '.join(hints),'recommendation':'Осмотрите участок и сопоставьте с журналом агроработ. Это сигнал, не диагноз болезни.'})
        active=[]
    for point in series:
        if detect and point['z'] is not None and point['z']<-1:
            active.append(point)
        else:
            finish()
    finish()
    latest=max(observed.values(),key=lambda x:x['date']) if observed else None
    return {'series':series,'anomalies':events,'latest':latest,'summary':{'observations':len(observed),'reconstructed':sum(x['reconstructed'] is not None for x in series),'unresolved':sum(x['ndvi'] is None for x in series),'anomalies':len(events),'latestNdvi':latest['ndvi'] if latest else None,'lastObservation':latest['date'] if latest else None},'method':'masked-neighbor residual model; linear fallback; max distance 30 days','limitations':['Аномалия — статистический сигнал, а не подтверждённая болезнь.','Химический состав почвы по этим ИК-каналам не определяется; BSI и SWIR — спектральные прокси.','Погодные данные ERA5 имеют сетку около 25 км, это не датчик непосредственно на участке.','Историческая норма требует минимум двух лет; при нехватке истории Z-score не рассчитывается.','Реконструкция после последнего наблюдения не является прогнозом; надёжность ниже измерений.']}
