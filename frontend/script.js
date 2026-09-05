const body = document.body;
const themeSwitch = document.querySelector('.theme-switch');
const themeColor = document.querySelector('meta[name="theme-color"]');
const sendCode = document.querySelector('.send-code');
const notice = document.querySelector('.form__notice');
const form = document.querySelector('#signup-form');
const accountLink = document.querySelector('.form-footer a');
const submit = document.querySelector('.submit');
const API_URL = window.FLORAMA_API_URL || 'http://89.111.171.30/api';
let mode = 'register';

const setTheme = (theme) => {
  const isLight = theme === 'light';
  body.classList.toggle('is-light', isLight);
  themeSwitch.setAttribute('aria-pressed', String(!isLight));
  themeColor.setAttribute('content', isLight ? '#ffffff' : '#202125');
  localStorage.setItem('florama-theme', theme);
};

const savedTheme = localStorage.getItem('florama-theme');
if (savedTheme) setTheme(savedTheme);

themeSwitch.addEventListener('click', () => {
  setTheme(body.classList.contains('is-light') ? 'dark' : 'light');
});

const showNotice = (message) => {
  notice.textContent = message;
  notice.classList.add('is-visible');
};

const api = async (path, payload) => {
  const url = `${API_URL}${path}`;
  console.info('[FLORAMA API] request', { url, payload: { ...payload, code: payload?.code ? '[hidden]' : undefined } });
  let response;
  try {
    response = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    });
  } catch (error) {
    console.error('[FLORAMA API] network error', { url, error });
    throw new Error(`Нет связи с сервером (${window.location.protocol}//api.crewloom.ru).`);
  }
  const data = await response.json().catch(() => ({}));
  console.info('[FLORAMA API] response', { url, status: response.status, data });
  if (!response.ok) throw new Error(data.error || 'Ошибка сервера.');
  return data;
};

accountLink.addEventListener('click', (event) => {
  event.preventDefault();
  mode = mode === 'register' ? 'login' : 'register';
  form.classList.toggle('is-login', mode === 'login');
  accountLink.textContent = mode === 'register' ? 'Уже есть аккаунт' : 'Создать аккаунт';
  submit.textContent = mode === 'register' ? 'Зарегистрироваться' : 'Войти';
  showNotice(mode === 'register' ? 'Режим регистрации.' : 'Режим входа.');
});

sendCode.addEventListener('click', async () => {
  const email = form.elements.email;
  if (!email.value || !email.validity.valid) {
    email.focus();
    showNotice('Введите корректный адрес почты.');
    return;
  }
  sendCode.disabled = true;
  try {
    await api('/auth/send-code', { email: email.value, mode });
    showNotice('Код отправлен. Проверьте почту.');
    form.elements.code.focus();
  } catch (error) {
    showNotice(error.message);
  } finally {
    setTimeout(() => { sendCode.disabled = false; }, 60000);
  }
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  try {
    const result = await api('/auth/verify-code', { ...data, mode });
    localStorage.setItem('florama-user', JSON.stringify(result.user));
    showNotice(mode === 'register' ? 'Регистрация завершена.' : 'Вход выполнен.');
  } catch (error) {
    showNotice(error.message);
  }
});
