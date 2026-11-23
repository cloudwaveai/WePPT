import {initializeAccount} from './account-session.js';
try {
  await initializeAccount();
  await import('./app.js');
} catch (error) {
  const target = document.querySelector('#app');
  if (target) target.textContent = error.message || '加载失败，请刷新后重试。';
}
