const body = document.body;
const themeSwitch = document.querySelector('.theme-switch');
const themeColor = document.querySelector('meta[name="theme-color"]');
const sendCode = document.querySelector('.send-code');
const notice = document.querySelector('.form__notice');
const form = document.querySelector('#signup-form');

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

sendCode.addEventListener('click', () => {
  const email = form.elements.email;
  if (!email.value || !email.validity.valid) {
    email.focus();
    showNotice('Введите корректный адрес почты.');
    return;
  }
  showNotice('Код отправлен. Проверьте почту.');
  form.elements.code.focus();
});

form.addEventListener('submit', (event) => {
  event.preventDefault();
  showNotice('Спасибо! Регистрация почти завершена.');
});
