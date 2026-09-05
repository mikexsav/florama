const screen = document.querySelector('#screen');
const body = document.body;
const themeButton = document.querySelector('.theme-button');
const accountButton = document.querySelector('.account-button');
const accountMenu = document.querySelector('#account-menu');
const modalBackdrop = document.querySelector('.modal-backdrop');
const modalContent = document.querySelector('#modal-content');
const toast = document.querySelector('.toast');
const navButtons = [...document.querySelectorAll('.nav-link')];
const appShell = document.querySelector('.app-shell');
const authScreen = document.querySelector('#auth-screen');
const authForm = document.querySelector('#auth-form');
const authNames = authForm.querySelector('.auth-form__names');
const authNotice = document.querySelector('#auth-notice');
const sendCodeButton = document.querySelector('#send-code');
const authModeSwitch = document.querySelector('#auth-mode-switch');
const authSubmit = document.querySelector('#auth-submit');
let currentView = 'dashboard', selectedPolygon = 'Восточное поле', toastTimer, modalLastTrigger;
let savedUser = JSON.parse(localStorage.getItem('florama-user') || 'null');
let authMode = 'register', satelliteMap;
const API_URL = window.FLORAMA_API_URL || 'http://89.111.171.30/api';
const icon = (name) => `<svg><use href="#i-${name}"/></svg>`;
const polygons = [
  { name: 'Поле 12А', region: 'Ростовская Область', area: '128 га', source: 'OpenStreetMap', date: '14.07.2025', anomalies: '3', status: 'warning', culture: 'Пшеница (озимая)', range: 'Апрель 2006 - Январь 2009' },
  { name: 'Поле 34В', region: 'Краснодарский Край', area: '95 га', source: 'Вручную', date: '11.08.2025', anomalies: '2', status: 'warning', culture: 'Кукуруза', range: 'Май 2009 - Декабрь 2015' },
  { name: 'Северный Участок', region: 'Ставропольский Край', area: '210 га', source: 'OpenStreetMap', date: '19.08.2025', anomalies: '0', status: 'normal', culture: 'Подсолнечник', range: 'Апрель 2016 - Июнь 2025' },
  { name: 'Восточное поле', region: 'Волгоградская Обл.', area: '67 га', source: 'Яндекс Map', date: '18.10.2025', anomalies: '1', status: 'alert', culture: 'Пшеница (озимая)', range: 'Апрель 2006 - Январь 2009' },
  { name: 'Южный массив', region: 'Ростовская Область', area: '158 га', source: 'OpenStreetMap', date: '25.03.2026', anomalies: '1', status: 'alert', culture: 'Ячмень', range: 'Март 2012 - Август 2025' },
];

function setTheme(theme) {
  const light = theme === 'light';
  body.classList.toggle('is-light', light);
  document.querySelector('meta[name="theme-color"]').content = light ? '#f5f6f5' : '#202125';
  themeButton.innerHTML = icon(light ? 'sun' : 'moon');
  localStorage.setItem('florama-dashboard-theme', theme);
}
function showToast(message) { clearTimeout(toastTimer); toast.textContent = message; toast.classList.add('is-visible'); toastTimer = setTimeout(() => toast.classList.remove('is-visible'), 3200); }
function status(status) { return `<span class="status status--${status}">${({ normal:'Норма', warning:'Отклонение', alert:'Аномалия' })[status]}</span>`; }
function metric(content, value, alert = false) { return `<div class="metric ${alert ? 'metric--red' : ''}"><span class="metric__start">${content}</span><span class="metric__value">${value}</span></div>`; }

function dashboard() { return `
  <div class="page-heading"><h1>Панель управления</h1><p>Обзор ваших проектов и сельскохозяйственных территорий</p></div>
  <div class="metrics"><button class="button-primary" type="button" data-modal="project">Новый проект</button>${metric(`${icon('field')}Проектов:`, '5')}${metric(`${icon('field')}Полигоны, Га`, '323')}${metric(`${icon('alert')}Аномалии`, '3', true)}${metric(`${icon('clock')}Последнее обновление`, '14.07.2025')}</div>
  <h2 class="projects-heading">Проекты</h2>
  <button class="project-card" type="button" data-view="project"><h2>Поле ИП Иванов</h2><div class="project-meta"><span>${icon('pin')}Ростовская Область</span><span>${icon('field')}3 полигона</span><span>${icon('layers')}ESA Sentinel-2</span></div><p class="project-description">Управляйте мониторингом, полигонами и аналитикой проекта</p><div class="project-area">${icon('field')}Площадь <strong>128 га</strong></div><div class="project-card__footer"><span class="detail-line">${icon('clock')}Последнее обновление</span><strong>14.07.2025</strong></div></button>`; }

function miniPolygon(p) { return `<button class="mini-polygon" type="button" data-open-polygon="${p.name}"><span class="mini-map"></span><span class="mini-polygon__name"><strong>${p.name}</strong><span class="mini-polygon__info"><span>${icon('pin')}${p.region}</span><span>${icon('layers')}${p.area}</span><span>${icon('calendar')}${p.date}</span></span></span>${status(p.status)}<span class="more-button">${icon('more')}</span></button>`; }
function project() {
  const projectPolygons = [polygons[2], polygons[4], { ...polygons[0], name:'Центральное поле', area:'28 га', status:'normal' }, { ...polygons[3], name:'Восточный массив', area:'7 га', status:'alert' }];
  return `<div class="crumbs"><span>Панель управления</span><span>Проекты</span><strong>Поле ИП Иванов</strong></div>
  <div class="project-intro"><h1>Поле ИП Иванов</h1><div class="project-meta"><span>${icon('pin')}Ростовская Область</span><span>${icon('field')}3 полигона</span><span>${icon('layers')}ESA Sentinel-2</span></div><p>Управляйте мониторингом, полигонами и аналитикой проекта</p></div>
  <div class="project-metrics"><div class="stat-chip"><span>${icon('field')}Полигоны</span><b>3</b></div><div class="stat-chip"><span>${icon('field')}Площадь</span><b>128 га</b></div><div class="stat-chip stat-chip--alert"><span>${icon('alert')}Внимание</span><b>1</b></div><div class="stat-chip"><span>${icon('clock')}Последнее обновление</span><b>14.07.2025</b></div></div>
  <div class="project-tabs"><button class="project-tab is-active" type="button" data-project-tab="overview">${icon('grid')}Обзор</button><button class="project-tab" type="button" data-project-tab="polygons">${icon('field')}Полигоны проекта</button><button class="project-tab" type="button" data-project-tab="analytics">${icon('chart')}Аналитика</button><button class="project-tab" type="button" data-project-tab="events">${icon('calendar')}События</button><button class="project-tab" type="button" data-project-tab="settings">${icon('settings')}Настройки проекта</button></div>
  <div id="project-tab-content" class="project-grid">${overviewContent(projectPolygons)}</div>`;
}
function overviewContent(list) { return `<section class="panel"><div class="panel__title"><h2>${icon('layers')}Полигоны проекта</h2><button class="text-link" data-view="polygons">Все полигоны ${icon('arrow')}</button></div><div class="project-polygon-list">${list.map(miniPolygon).join('')}</div></section><div><section class="panel state-panel"><div class="panel__title"><h2>${icon('chart')}Состояние проекта</h2></div>${barRows()}</section><section class="panel events-panel">${events()}</section></div>`; }
function barRows() { return `<div class="state-bars"><div class="state-row"><span class="state-row__label">${icon('chart')}Норма</span><span class="bar"><span style="width:67%"></span></span><b>67%</b></div><div class="state-row"><span class="state-row__label">${icon('settings')}Отклонение</span><span class="bar bar--yellow"><span style="width:25%"></span></span><b>25%</b></div><div class="state-row"><span class="state-row__label">${icon('alert')}Аномалия</span><span class="bar bar--red"><span style="width:8%"></span></span><b>8%</b></div></div>`; }
function events() { return `<div class="panel__title"><h2>${icon('clock')}Последние события</h2><button class="text-link" data-project-tab="events">Все события ${icon('arrow')}</button></div><div class="event-list"><div class="event"><span class="event__icon">${icon('image')}</span><span><strong>Получен новый снимок</strong><span>Поле ИП Иванов • 3 полигона</span></span><time>25.03.2026&nbsp;&nbsp;10:24</time></div><div class="event event--alert"><span class="event__icon">${icon('alert')}</span><span><strong>Обнаружено отклонение NDVI</strong><span>Полигон: Южный кластер</span></span><time>18.10.2025&nbsp;&nbsp;14:17</time></div></div>`; }

function rows(items) { return items.map(p => `<button class="polygon-row ${p.name === selectedPolygon ? 'is-selected' : ''}" type="button" data-select-polygon="${p.name}"><span><strong>${p.name}</strong><span class="polygon-row__region">${p.region}</span></span><span class="polygon-row__fact polygon-row__area">${p.area}</span><span class="polygon-row__source">${p.source}</span><span class="polygon-row__date">${p.date}</span><span class="anomaly-count ${p.anomalies === '0' ? 'is-zero' : ''}">${p.anomalies}</span><span class="more-button">${icon('more')}</span></button>`).join('') || '<p>Ничего не найдено. Попробуйте другой запрос.</p>'; }
function details(p) { return `<div class="map-details"><div id="satellite-map" class="polygon-map" role="application" aria-label="Спутниковая карта полигона ${p.name}"></div><div class="map-details__rows"><div class="map-details__row">${icon('field')}<span>Площадь</span><span>${p.area}</span></div><div class="map-details__row">${icon('field')}<span>Культура</span><span>${p.culture}</span></div><div class="map-details__row">${icon('globe')}<span>Источник</span><span>ESA WorldCereal</span></div><div class="map-details__row">${icon('calendar')}<span>Последний источник</span><span>11.01.2008</span></div><div class="map-details__row">${icon('cloud')}<span>Облачность</span><span>12%</span></div><div class="map-details__row">${icon('chart')}<span>Временной ряд</span><span>${p.range}</span></div></div></div>`; }
function polygonsView() { const p = polygons.find(x=>x.name===selectedPolygon) || polygons[0]; return `<div class="page-heading"><h1>Полигоны</h1><p>Управляйте сельскохозяйственными контурами и территориями наблюдения</p></div><div class="polygons-layout"><section><div class="list-actions"><button class="button-primary" data-modal="polygon">Новый полигон</button><label class="search">${icon('search')}<input id="polygon-search" type="search" placeholder="Поиск по названию или региону..." autocomplete="off" /></label></div><h2 class="list-heading">Список ваших полигонов</h2><div id="polygon-list" class="polygon-list">${rows(polygons)}</div></section><aside id="polygon-details">${details(p)}</aside></div>`; }

function polygonCoordinates(name) {
  const centers = { 'Поле 12А':[47.239,39.721], 'Поле 34В':[45.035,38.976], 'Северный Участок':[45.251,42.130], 'Восточное поле':[48.706,44.516], 'Южный массив':[47.095,39.534] };
  const center = centers[name] || [47.239,39.721];
  const [lat,lng] = center;
  return [[lat-.019,lng-.027],[lat+.015,lng-.019],[lat+.024,lng+.022],[lat+.003,lng+.034],[lat-.021,lng+.012],[lat-.019,lng-.027]];
}
function initSatelliteMap() {
  const node = document.querySelector('#satellite-map');
  if (!node) return;
  if (!window.L) { node.innerHTML = '<p class="map-unavailable">Не удалось загрузить спутниковый слой. Проверьте подключение к интернету.</p>'; return; }
  satelliteMap?.remove();
  satelliteMap = L.map(node, { zoomControl:false, attributionControl:true, scrollWheelZoom:false });
  L.control.zoom({ position:'bottomright' }).addTo(satelliteMap);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom:19, attribution:'Tiles © Esri' }).addTo(satelliteMap);
  const shape = polygonCoordinates(selectedPolygon);
  const outline = L.polygon(shape, { color:'#2583ff', weight:3, fillColor:'#2b83eb', fillOpacity:.22 }).addTo(satelliteMap);
  const anomaly = L.circle([shape[2][0]-.007,shape[2][1]-.01], { radius:650, color:'#ff3d45', weight:0, fillColor:'#ff3d45', fillOpacity:.42 }).addTo(satelliteMap);
  const warning = L.circle([shape[4][0]+.004,shape[4][1]+.012], { radius:530, color:'#ffc247', weight:0, fillColor:'#ffc247', fillOpacity:.43 }).addTo(satelliteMap);
  outline.bindTooltip(selectedPolygon, { permanent:true, direction:'center', className:'map-label' }).openTooltip();
  satelliteMap.fitBounds(outline.getBounds(), { padding:[22,22], maxZoom:14 });
  requestAnimationFrame(() => satelliteMap.invalidateSize());
}

function analytics() { return `<div class="page-heading"><h1>Аналитика</h1><p>Мониторинг временных рядов и аномалий по выбранным полигонам</p></div><div class="filters"><div class="filter">${icon('field')}<label>Полигон</label><select id="analytics-polygon">${polygons.map(p=>`<option>${p.name}</option>`).join('')}</select></div><div class="filter">${icon('clock')}<label>Период</label><select id="analytics-period"><option>Апрель - Июнь 2025</option><option>Январь - Март 2025</option><option>Июль - Сентябрь 2024</option></select></div><div class="filter">${icon('cloud')}<label>Источник</label><select id="analytics-source"><option>ESA Sentinel-2</option><option>Landsat 8</option><option>MODIS</option></select></div></div>
  <div class="analytics-metrics">${analyticCard('chart','Текущий NDVI','0.72 <small>+0.05</small>','Относительно прошлого снимка')}${analyticCard('chart','Отклонение от нормы','−0.08','Ниже климатической нормы','yellow')}${analyticCard('field','Пропуски восстановлены','14','точек в временном ряду')}${analyticCard('alert','Аномальные зоны','3','требуют внимания','alert')}</div>
  <div class="analytics-content"><section class="panel donut-panel"><div class="panel__title"><h2>Распределение состояний</h2></div><div class="donut-wrap"><div class="donut"><span class="donut__center">128 га<small>Общая площадь</small></span></div><div class="legend"><div><span>Норма</span><span class="normal">72%</span></div><div><span>Умеренное отклонение</span><span class="warning">19%</span></div><div><span>Критическая аномалия</span><span class="alert">9%</span></div></div></div></section><section class="panel quality-panel"><div class="panel__title"><h2>Качество данных</h2></div><p class="subtle">на 14.07.2025 10:24 UTC+3</p><div class="quality-metrics"><div class="quality-metric"><h3>Облачность</h3><strong>12%</strong><span>в среднем</span></div><div class="quality-metric"><h3>Снимки</h3><strong>18</strong><span>за период</span></div></div></section></div><button class="button-secondary analytics-action" data-view="polygons">Открыть на карте</button>`; }
function analyticCard(i,title,val,sub,kind='') { return `<article class="analytics-card analytics-card--${kind}"><span class="analytics-card__icon">${icon(i)}</span><div><h2>${title}</h2><strong class="analytics-card__value">${val}</strong></div><p>${sub}</p></article>`; }

function settings() { const restore=localStorage.getItem('florama-restore')!=='false', anomaly=localStorage.getItem('florama-anomaly')!=='false'; const name=savedUser?.firstName?`${savedUser.firstName} ${savedUser.lastName||''}`.trim():'Михаил Савченко', mail=savedUser?.email||'mmmsss717171@gmail.com'; return `<div class="page-heading"><h1>Настройки</h1><p>Параметры мониторинга спутниковых данных и анализа территорий</p></div><div class="settings-grid"><section class="settings-card profile-card"><span class="profile-brand"><strong>Λ</strong> <span>andrometa</span> ID</span><div class="profile-card__head"><span class="profile-avatar">${icon('user')}</span><h2>${name}</h2></div><div class="profile-card__details"><p class="inline-icon">${icon('image')}${mail}</p><p>ID: <strong>14a454c29</strong></p><p>Статус: <span class="protected">Защищено</span></p></div><button class="button-primary" data-modal="account">Управление аккаунтом</button></section><section class="settings-card"><h2>Анализ</h2><p>Настройки обработки и анализа данных</p><div class="switch-list">${switchRow('restore',restore,'Восстанавливать пропуски временного ряда','Использовать интерполяцию для заполнения отсутствующих данных.')}${switchRow('anomaly',anomaly,'Выявлять аномалии растительности','Автоматически находить отклонения от типичных значений.')}</div></section></div>`; }
function switchRow(key,on,title,sub) { return `<div class="switch-row"><button class="switch ${on?'is-on':''}" type="button" data-setting="${key}" aria-pressed="${on}"><span></span></button><div class="switch-copy"><strong>${title}</strong><span>${sub}</span></div></div>`; }

function render(view) { currentView=view; const pages={dashboard,project,polygons:polygonsView,analytics,settings}; screen.innerHTML=pages[view](); screen.classList.remove('screen'); void screen.offsetWidth; screen.classList.add('screen'); navButtons.forEach(n=>n.classList.toggle('is-active',n.dataset.view===(view==='project'?'dashboard':view))); body.classList.remove('menu-open'); window.scrollTo({top:0,behavior:'smooth'}); if(view === 'polygons') requestAnimationFrame(initSatelliteMap); }
function projectTab(tab) { const c=document.querySelector('#project-tab-content'); if(tab==='overview') return render('project'); const templates={polygons:`<section class="panel"><div class="panel__title"><h2>${icon('field')}Полигоны проекта</h2><button class="button-primary" data-modal="polygon">Добавить полигон</button></div><div class="project-polygon-list">${polygons.slice(0,4).map(miniPolygon).join('')}</div></section><section class="panel"><div class="panel__title"><h2>${icon('chart')}Сводка полигонов</h2></div><p class="project-description">Выберите полигон, чтобы перейти к детальной карте, состоянию растительности и истории наблюдений.</p><button class="button-secondary" data-view="polygons">Открыть все полигоны</button></section>`,analytics:`<section class="panel"><div class="panel__title"><h2>${icon('chart')}Аналитика проекта</h2></div><p class="project-description">Агрегированные показатели по трём полигонам за текущий сезон.</p>${barRows()}</section><section class="panel"><div class="panel__title"><h2>Перейти к отчёту</h2></div><p class="project-description">Фильтруйте состояние, период и источник данных в общем разделе аналитики.</p><button class="button-primary" data-view="analytics">Открыть аналитику</button></section>`,events:`<section class="panel" style="grid-column:1/-1">${events()}<div class="event"><span class="event__icon">${icon('check')}</span><span><strong>Временной ряд обновлён</strong><span>Успешно восстановлено 14 пропусков</span></span><time>14.07.2025&nbsp;&nbsp;10:24</time></div></section>`,settings:`<section class="panel" style="grid-column:1/-1"><div class="panel__title"><h2>${icon('settings')}Настройки проекта</h2></div><p class="project-description">Источник данных: ESA Sentinel-2. Уведомления о значимых аномалиях включены.</p><button class="button-primary" data-view="settings">Настроить мониторинг</button></section>`}; c.innerHTML=templates[tab]; }

function openModal(type, trigger) { modalLastTrigger=trigger; const m={project:`<h2 id="modal-title">Новый проект</h2><p>Создайте пространство для мониторинга полей и аналитики.</p><form data-form="project"><label>Название проекта<input name="name" placeholder="Например, Поле ИП Иванов" required></label><label>Регион<input name="region" placeholder="Ростовская область" required></label><button class="button-primary">Создать проект</button></form>`,polygon:`<h2 id="modal-title">Новый полигон</h2><p>Добавьте территорию в список наблюдения.</p><form data-form="polygon"><label>Название полигона<input name="name" placeholder="Поле 56А" required></label><label>Регион<input name="region" placeholder="Ростовская область" required></label><label>Площадь<input name="area" type="number" min="1" placeholder="42" required></label><button class="button-primary">Добавить полигон</button></form>`,account:`<h2 id="modal-title">Управление аккаунтом</h2><p>Укажите имя, которое будет отображаться в кабинете.</p><form data-form="account"><label>Имя<input name="firstName" value="${savedUser?.firstName||'Михаил'}" required></label><label>Фамилия<input name="lastName" value="${savedUser?.lastName||'Савченко'}" required></label><button class="button-primary">Сохранить изменения</button></form>`}; modalContent.innerHTML=m[type]; modalBackdrop.hidden=false; requestAnimationFrame(()=>modalContent.querySelector('input')?.focus()); }
function closeModal() { if(!modalBackdrop.hidden){modalBackdrop.hidden=true;modalLastTrigger?.focus();} }

document.addEventListener('click',e=>{ const view=e.target.closest('[data-view]'); if(view){render(view.dataset.view);accountMenu.hidden=true;return} const modal=e.target.closest('[data-modal]'); if(modal){openModal(modal.dataset.modal,modal);return} const p=e.target.closest('[data-select-polygon],[data-open-polygon]'); if(p){selectedPolygon=p.dataset.selectPolygon||p.dataset.openPolygon;render('polygons');return} const tab=e.target.closest('[data-project-tab]'); if(tab){document.querySelectorAll('.project-tab').forEach(x=>x.classList.toggle('is-active',x===tab));projectTab(tab.dataset.projectTab);return} const setting=e.target.closest('[data-setting]'); if(setting){const key=`florama-${setting.dataset.setting}`,on=!setting.classList.contains('is-on');setting.classList.toggle('is-on',on);setting.setAttribute('aria-pressed',on);localStorage.setItem(key,on);showToast(on?'Настройка включена.':'Настройка выключена.');return} if(e.target.closest('.modal__close')||e.target===modalBackdrop){closeModal();return} if(e.target.closest('[data-logout]')){accountMenu.hidden=true;showToast('Вы вышли из аккаунта. Демо-данные остаются доступны.');return} if(!e.target.closest('.account-wrap'))accountMenu.hidden=true; });
document.addEventListener('input',e=>{if(e.target.id==='polygon-search'){const q=e.target.value.toLocaleLowerCase('ru').trim();document.querySelector('#polygon-list').innerHTML=rows(polygons.filter(p=>`${p.name} ${p.region}`.toLocaleLowerCase('ru').includes(q)));}});
document.addEventListener('change',e=>{if(['analytics-polygon','analytics-period','analytics-source'].includes(e.target.id))showToast(e.target.id==='analytics-polygon'?`Данные обновлены: ${e.target.value}.`:'Фильтры применены к аналитике.');});
document.addEventListener('submit',e=>{const f=e.target.closest('[data-form]');if(!f)return;e.preventDefault();const v=Object.fromEntries(new FormData(f));if(f.dataset.form==='polygon'){const p={name:v.name,region:v.region,area:`${v.area} га`,source:'Вручную',date:new Intl.DateTimeFormat('ru-RU').format(new Date()),anomalies:'0',status:'normal',culture:'Не выбрана',range:'Нет данных'};polygons.unshift(p);selectedPolygon=p.name;closeModal();render('polygons');showToast(`Полигон «${p.name}» добавлен.`)}else if(f.dataset.form==='project'){closeModal();render('project');showToast(`Проект «${v.name}» создан.`)}else{savedUser={...savedUser,...v,email:savedUser?.email||'mmmsss717171@gmail.com'};localStorage.setItem('florama-user',JSON.stringify(savedUser));closeModal();render('settings');showToast('Данные аккаунта сохранены.')}});
accountButton.addEventListener('click',()=>{accountMenu.hidden=!accountMenu.hidden;accountButton.setAttribute('aria-expanded',!accountMenu.hidden)});themeButton.addEventListener('click',()=>setTheme(body.classList.contains('is-light')?'dark':'light'));document.querySelector('.auth-theme').addEventListener('click',()=>setTheme(body.classList.contains('is-light')?'dark':'light'));document.querySelector('.mobile-menu').addEventListener('click',()=>body.classList.toggle('menu-open'));document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeModal();accountMenu.hidden=true;body.classList.remove('menu-open')}});

function updateAccountLabels() {
  const email = savedUser?.email || 'yourmail@gmail.com';
  const name = savedUser?.firstName ? `${savedUser.firstName} ${savedUser.lastName || ''}`.trim() : 'Михаил Савченко';
  document.querySelector('.account-name').textContent = email;
  accountMenu.querySelector('strong').textContent = name;
  accountMenu.querySelector('span').textContent = email;
}
function setAuthMode(mode) {
  authMode = mode;
  const login = mode === 'login';
  authForm.classList.toggle('is-login', login);
  authNames.inert = login;
  authNames.setAttribute('aria-hidden', String(login));
  authForm.elements.firstName.required = !login;
  authForm.elements.lastName.required = !login;
  document.querySelector('#auth-title').textContent = login ? 'С возвращением' : 'Создайте аккаунт';
  document.querySelector('#auth-description').textContent = login ? 'Введите почту и код из письма, чтобы открыть кабинет.' : 'Начните отслеживать состояние своих полей и получать данные со спутников.';
  authSubmit.textContent = login ? 'Войти в кабинет' : 'Зарегистрироваться';
  authModeSwitch.textContent = login ? 'Создать аккаунт' : 'Уже есть аккаунт';
  authNotice.textContent = '';
}
function showAuth() { appShell.hidden = true; authScreen.hidden = false; setAuthMode('register'); }
function enterApp() { authScreen.hidden = true; appShell.hidden = false; updateAccountLabels(); render('dashboard'); }
async function authApi(path, payload) {
  let response;
  try { response = await fetch(`${API_URL}${path}`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) }); }
  catch { throw new Error('Нет связи с сервером. Повторите попытку позже.'); }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || 'Не удалось выполнить запрос.');
  return result;
}
function authMessage(text, state = '') { authNotice.textContent = text; authNotice.dataset.state = state; }
authModeSwitch.addEventListener('click', () => setAuthMode(authMode === 'register' ? 'login' : 'register'));
sendCodeButton.addEventListener('click', async () => {
  const email = authForm.elements.email;
  if (!email.validity.valid) { email.reportValidity(); return; }
  sendCodeButton.disabled = true; authMessage('Отправляем код…');
  try { await authApi('/auth/send-code', { email:email.value, mode:authMode }); authMessage('Код отправлен. Проверьте почту.', 'success'); authForm.elements.code.focus(); }
  catch (error) { authMessage(error.message, 'error'); }
  finally { setTimeout(() => { sendCodeButton.disabled = false; }, 60000); }
});
authForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (!authForm.reportValidity()) return;
  const values = Object.fromEntries(new FormData(authForm));
  authSubmit.disabled = true; authMessage('Проверяем код…');
  try {
    const result = await authApi('/auth/verify-code', { ...values, mode:authMode });
    savedUser = result.user; localStorage.setItem('florama-user', JSON.stringify(result.user)); localStorage.setItem('florama-token', result.token);
    enterApp(); showToast(authMode === 'login' ? 'Вы вошли в кабинет.' : 'Аккаунт создан. Добро пожаловать!');
  } catch (error) { authMessage(error.message, 'error'); }
  finally { authSubmit.disabled = false; }
});
document.addEventListener('click', event => {
  if (!event.target.closest('[data-logout]')) return;
  savedUser = null; localStorage.removeItem('florama-user'); localStorage.removeItem('florama-token'); accountMenu.hidden = true; showAuth();
});

setTheme(localStorage.getItem('florama-dashboard-theme') || 'dark');
if (savedUser) enterApp(); else showAuth();
