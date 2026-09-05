"""HTTP API кабинета. Все данные и аналитические решения принадлежат серверу."""
import json
import csv
import io
import logging
import os
import re
import secrets
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from flask import Flask, g, jsonify, request, send_file
from flask_cors import CORS
from werkzeug.exceptions import HTTPException, BadRequest, Forbidden, NotFound
from werkzeug.middleware.proxy_fix import ProxyFix
from auth import auth, require_user, payload, text_field, public_user, limit
from store import transaction, migrate, dumps
from geo import validate_geometry
from providers import geocode, farmland


def csv_rows(upload):
    """Читает только компактный CSV участков, не создавая записи до полной валидации."""
    raw=upload.read()
    if len(raw)>3_000_000:
        raise ValueError('CSV не должен превышать 3 МБ.')
    try:
        source=raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('Сохраните CSV в UTF-8.') from exc
    try:
        dialect=csv.Sniffer().sniff(source[:4096],delimiters=',;\t')
    except csv.Error:
        dialect=csv.excel
    rows=list(csv.DictReader(io.StringIO(source),dialect=dialect))
    if not rows:
        raise ValueError('CSV пуст или в нём нет заголовка.')
    if len(rows)>50:
        raise ValueError('За один импорт можно добавить не более 50 участков.')
    result=[]
    for index,row in enumerate(rows,start=2):
        values={(key or '').strip().lower():str(value or '').strip() for key,value in row.items()}
        geometry_raw=values.get('geometry') or values.get('geojson')
        try:
            if geometry_raw:
                geometry=json.loads(geometry_raw)
            elif values.get('wkt'):
                from shapely import from_wkt
                from shapely.geometry import mapping
                geometry=mapping(from_wkt(values['wkt']))
            elif all(values.get(key) for key in ('west','south','east','north')):
                west,south,east,north=(float(values[key]) for key in ('west','south','east','north'))
                geometry={'type':'Polygon','coordinates':[[[west,south],[east,south],[east,north],[west,north],[west,south]]]}
            else:
                raise ValueError('нужна колонка geometry/geojson, wkt или west,south,east,north')
            geo=validate_geometry(geometry)
        except Exception as exc:
            raise ValueError(f'Строка {index}: {exc}') from exc
        result.append({'geo':geo,'name':values.get('name') or f'Участок {index-1}','region':values.get('region',''),'crop':values.get('crop',''),'cadastral':values.get('cadastralnumber') or values.get('cadastral_number','')})
    return result


def create_app(config=None):
    app=Flask(__name__)
    app.config.update(DB_PATH=os.getenv('DB_PATH','/opt/florama/data/florama.sqlite3'),SECRET_KEY=os.getenv('APP_SECRET',''),COOKIE_SECURE=os.getenv('COOKIE_SECURE','true').lower()=='true',MAX_CONTENT_LENGTH=16*1024*1024,DATA_DIR=os.getenv('DATA_DIR','/opt/florama/data'))
    if config:
        app.config.update(config)
    if len(app.config['SECRET_KEY'])<32:
        raise RuntimeError('Задайте APP_SECRET длиной не менее 32 символов в окружении сервера.')
    migrate(app.config['DB_PATH'])
    # API слушает только loopback; ровно один доверенный nginx перед приложением.
    app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1)
    origins=os.getenv('APP_ORIGINS','https://crewloom.ru,https://www.crewloom.ru').split(',')
    CORS(app,resources={r'/api/*':{'origins':origins}},supports_credentials=True,expose_headers=['X-Request-ID'])
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    app.register_blueprint(auth)

    @app.before_request
    def before():
        g.request_id=secrets.token_hex(8)
        g.started=time.monotonic()
        origin=request.headers.get('Origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin and origin not in origins and origin!=request.host_url.rstrip('/'):
            raise Forbidden('Запрос с этого сайта не разрешён.')

    @app.after_request
    def after(response):
        response.headers['X-Request-ID']=g.get('request_id','-')
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Cache-Control']='no-store'
        app.logger.info('request_id=%s method=%s path=%s status=%s duration_ms=%s',g.get('request_id','-'),request.method,request.path,response.status_code,round((time.monotonic()-g.get('started',time.monotonic()))*1000))
        return response

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc,HTTPException):
            return jsonify(error=exc.description,requestId=g.get('request_id','-')),exc.code
        app.logger.exception('request_id=%s unhandled type=%s',g.get('request_id','-'),type(exc).__name__)
        return jsonify(error='Ошибка сервера. Сохраните ID ошибки для диагностики.',requestId=g.get('request_id','-')),500

    def db(immediate=False):
        return transaction(app.config['DB_PATH'],immediate)

    def owned(c,table,object_id):
        row=c.execute(f'SELECT * FROM {table} WHERE id=? AND user_id=?',(object_id,g.user['id'])).fetchone()
        if not row:
            raise NotFound('Объект не найден.')
        return row

    def polygon_json(row):
        result=dict(row); result['geometry']=json.loads(result['geometry'])
        result.pop('user_id',None)
        return result

    @app.get('/api/health')
    def health():
        with db() as c:
            c.execute('SELECT 1').fetchone()
        return jsonify(status='ok',version='2.0',database='ok')

    @app.patch('/api/profile')
    @require_user
    def profile():
        data=payload()
        first=text_field(data.get('firstName',''),'Имя',80,True)
        last=text_field(data.get('lastName',''),'Фамилия',80,True)
        with db() as c:
            c.execute('UPDATE users SET first_name=?,last_name=? WHERE id=?',(first,last,g.user['id']))
            row=c.execute('SELECT * FROM users WHERE id=?',(g.user['id'],)).fetchone()
        return jsonify(user=public_user(row))

    @app.route('/api/settings',methods=['GET','PATCH'])
    @require_user
    def settings():
        with db() as c:
            row=c.execute('SELECT settings FROM preferences WHERE user_id=?',(g.user['id'],)).fetchone()
            values={'restore':True,'anomaly':True,**(json.loads(row['settings']) if row else {})}
            if request.method=='PATCH':
                data=payload()
                if any(k not in ('restore','anomaly') or not isinstance(v,bool) for k,v in data.items()):
                    raise BadRequest('Параметры должны быть логическими restore/anomaly.')
                values.update(data)
                c.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',(g.user['id'],dumps(values)))
        return jsonify(settings=values)

    @app.route('/api/projects',methods=['GET','POST'])
    @require_user
    def projects():
        with db() as c:
            if request.method=='POST':
                data=payload(); project_id=uuid.uuid4().hex
                c.execute('INSERT INTO projects VALUES (?,?,?,?,?)',(project_id,g.user['id'],text_field(data.get('name',''),'Название',120,True),text_field(data.get('region',''),'Регион',200),int(time.time())))
            values=[dict(v) for v in c.execute('SELECT id,name,region,created_at FROM projects WHERE user_id=? ORDER BY created_at DESC',(g.user['id'],))]
        return jsonify(projects=values),201 if request.method=='POST' else 200

    @app.delete('/api/projects/<object_id>')
    @require_user
    def delete_project(object_id):
        with db() as c:
            owned(c,'projects',object_id)
            c.execute('DELETE FROM projects WHERE id=?',(object_id,))
        return jsonify(message='Проект удалён, участки сохранены без проекта.')

    @app.route('/api/polygons',methods=['GET','POST'])
    @require_user
    def polygons():
        if request.method=='POST':
            data=payload()
            try:
                geo=validate_geometry(data.get('geometry'))
            except (ValueError,TypeError,KeyError) as exc:
                raise BadRequest(str(exc)) from exc
            cad=text_field(data.get('cadastralNumber',''),'Кадастровый номер',40)
            if cad and not re.fullmatch(r'\d{2}:\d{2}:\d{6,7}:\d{1,10}',cad):
                raise BadRequest('Формат кадастрового номера: 61:44:0000000:123.')
            source=data.get('source','manual')
            if source not in ('manual','OpenStreetMap','cadastre','GeoJSON'):
                raise BadRequest('Неизвестный источник границ.')
            with db() as c:
                if c.execute('SELECT COUNT(*) FROM polygons WHERE user_id=?',(g.user['id'],)).fetchone()[0]>=100:
                    raise BadRequest('Лимит аккаунта: 100 участков.')
                project_id=data.get('projectId') or None
                if project_id:
                    owned(c,'projects',project_id)
                object_id=uuid.uuid4().hex
                c.execute('INSERT INTO polygons VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(object_id,g.user['id'],project_id,text_field(data.get('name',''),'Название',120,True),text_field(data.get('region',''),'Регион',200),text_field(data.get('crop',''),'Культура',80),dumps(geo['geometry']),geo['area_ha'],geo['latitude'],geo['longitude'],source,cad,int(time.time())))
                row=owned(c,'polygons',object_id)
            return jsonify(polygon=polygon_json(row)),201
        with db() as c:
            values=[polygon_json(v) for v in c.execute('SELECT * FROM polygons WHERE user_id=? ORDER BY created_at DESC',(g.user['id'],))]
            for item in values:
                last=c.execute('SELECT id,result FROM analyses WHERE polygon_id=? ORDER BY created_at DESC LIMIT 1',(item['id'],)).fetchone()
                if last:
                    item['analysisId']=last['id']; item['summary']=json.loads(last['result'])['summary']
        return jsonify(polygons=values)

    @app.delete('/api/polygons/<object_id>')
    @require_user
    def delete_polygon(object_id):
        with db(immediate=True) as c:
            owned(c,'polygons',object_id)
            if c.execute("SELECT 1 FROM jobs WHERE polygon_id=? AND status IN ('queued','running')",(object_id,)).fetchone():
                raise BadRequest('Дождитесь завершения обработки перед удалением участка.')
            c.execute('DELETE FROM polygons WHERE id=?',(object_id,))
        return jsonify(message='Участок и его результаты удалены.')

    @app.post('/api/polygons/import-csv')
    @require_user
    def import_polygons_csv():
        """Импорт контуров с атомарной записью: ошибочная строка не создаёт частичный набор."""
        limit('polygon-csv:'+str(g.user['id']),6,3600)
        upload=request.files.get('file')
        if not upload or not upload.filename.lower().endswith('.csv'):
            raise BadRequest('Выберите CSV-файл участков.')
        try:
            rows=csv_rows(upload)
        except ValueError as exc:
            raise BadRequest(str(exc)) from exc
        project_id=request.form.get('projectId') or None
        with db(immediate=True) as c:
            if project_id:
                owned(c,'projects',project_id)
            existing=c.execute('SELECT COUNT(*) FROM polygons WHERE user_id=?',(g.user['id'],)).fetchone()[0]
            if existing+len(rows)>100:
                raise BadRequest(f'Лимит аккаунта: 100 участков. Можно добавить ещё {100-existing}.')
            now=int(time.time()); created=[]
            for row in rows:
                cad=text_field(row['cadastral'],'Кадастровый номер',40)
                if cad and not re.fullmatch(r'\d{2}:\d{2}:\d{6,7}:\d{1,10}',cad):
                    raise BadRequest(f'Некорректный кадастровый номер: {cad}.')
                object_id=uuid.uuid4().hex; geo=row['geo']
                c.execute('INSERT INTO polygons VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(object_id,g.user['id'],project_id,text_field(row['name'],'Название',120,True),text_field(row['region'],'Регион',200),text_field(row['crop'],'Культура',80),dumps(geo['geometry']),geo['area_ha'],geo['latitude'],geo['longitude'],'CSV',cad,now))
                created.append(object_id)
        return jsonify(created=len(created),polygonIds=created),201

    @app.post('/api/polygons/<object_id>/analyze')
    @require_user
    def analyze(object_id):
        data=payload()
        try:
            end=date.fromisoformat(data.get('end',str(date.today()-timedelta(days=1))))
            start=date.fromisoformat(data.get('start',str(end-timedelta(days=89))))
            if not date(2019,1,1)<=start<=end<date.today() or (end-start).days>366:
                raise ValueError()
        except (ValueError,TypeError):
            raise BadRequest('Период: от 2019 года до вчера, не более 367 дней.')
        with db(immediate=True) as c:
            owned(c,'polygons',object_id)
            previous=c.execute("SELECT id FROM jobs WHERE user_id=? AND status IN ('queued','running')",(g.user['id'],)).fetchone()
            if previous:
                return jsonify(jobId=previous['id'],message='Уже выполняется задача. Дождитесь завершения.'),202
            job_id=uuid.uuid4().hex; now=int(time.time())
            c.execute('INSERT INTO jobs(id,user_id,polygon_id,kind,payload,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',(job_id,g.user['id'],object_id,'monitor',dumps({'start':str(start),'end':str(end)}),now,now))
        return jsonify(jobId=job_id),202

    @app.get('/api/jobs')
    @require_user
    def jobs():
        with db() as c:
            values=[dict(v) for v in c.execute('SELECT id,polygon_id,kind,status,progress,message,result,created_at,updated_at FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 30',(g.user['id'],))]
        for item in values:
            item['result']=json.loads(item['result']) if item['result'] else None
        return jsonify(jobs=values)

    @app.get('/api/analyses/<object_id>')
    @require_user
    def analysis(object_id):
        with db() as c:
            row=c.execute('SELECT a.result FROM analyses a JOIN polygons p ON p.id=a.polygon_id WHERE a.id=? AND p.user_id=?',(object_id,g.user['id'])).fetchone()
        if not row:
            raise NotFound('Результат не найден.')
        return jsonify(analysis=json.loads(row['result']))

    @app.get('/api/regions')
    @require_user
    def regions():
        query=text_field(request.args.get('q',''),'Регион',150,True)
        limit('geocode-global',1,1)
        try:
            return jsonify(regions=geocode(query))
        except Exception as exc:
            app.logger.warning('geocoder_failure type=%s',type(exc).__name__)
            return jsonify(error='Поиск региона недоступен. Переместите карту вручную.',requestId=g.request_id),502

    @app.get('/api/farmland')
    @require_user
    def fields():
        limit('farmland:'+str(g.user['id']),6,60)
        try:
            bounds=[float(x) for x in request.args.get('bbox','').split(',')]
            if len(bounds)!=4:
                raise ValueError('Ожидается bbox west,south,east,north.')
            return jsonify(farmland(bounds))
        except ValueError as exc:
            raise BadRequest(str(exc)) from exc
        except Exception as exc:
            app.logger.warning('farmland_failure type=%s',type(exc).__name__)
            return jsonify(error='Поиск контуров недоступен. Можно нарисовать участок вручную.',requestId=g.request_id),502

    @app.post('/api/batch')
    @require_user
    def batch():
        limit('batch:'+str(g.user['id']),6,3600)
        upload=request.files.get('file')
        if not upload or not upload.filename.lower().endswith('.csv'):
            raise BadRequest('Выберите CSV с контрольными пропусками.')
        job_id=uuid.uuid4().hex
        directory=Path(app.config['DATA_DIR'])/'jobs'/job_id
        with db(immediate=True) as c:
            if c.execute("SELECT 1 FROM jobs WHERE user_id=? AND status IN ('queued','running')",(g.user['id'],)).fetchone():
                raise BadRequest('Дождитесь завершения текущей задачи.')
            directory.mkdir(parents=True,mode=0o700)
            input_path=directory/'input.csv'; output_path=directory/'submission.csv'
            upload.save(input_path); input_path.chmod(0o600)
            now=int(time.time())
            c.execute('INSERT INTO jobs(id,user_id,kind,payload,created_at,updated_at) VALUES (?,?,?,?,?,?)',(job_id,g.user['id'],'batch',dumps({'input':str(input_path),'output':str(output_path)}),now,now))
        return jsonify(jobId=job_id),202

    @app.get('/api/jobs/<object_id>/download')
    @require_user
    def download(object_id):
        with db() as c:
            row=owned(c,'jobs',object_id)
        if row['kind']!='batch' or row['status']!='done':
            raise NotFound('Файл пока не готов.')
        path=Path(app.config['DATA_DIR'])/'jobs'/object_id/'submission.csv'
        return send_file(path,as_attachment=True,download_name='submission.csv',mimetype='text/csv')

    @app.get('/api/research')
    @require_user
    def research():
        path=Path(__file__).parent/'models'/'metrics.json'
        return jsonify(metrics=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None)

    @app.post('/api/client-errors')
    @require_user
    def client_errors():
        limit('errors:'+str(g.user['id']),20,60)
        data=payload()
        kind=re.sub('[^a-zA-Z0-9_-]','',str(data.get('kind','unknown'))[:40])
        app.logger.warning('client_error user_id=%s kind=%s request_id=%s',g.user['id'],kind,g.request_id)
        return jsonify(received=True)

    return app


if __name__=='__main__':
    create_app().run(host='127.0.0.1',port=8000)
