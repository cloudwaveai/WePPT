let account = null;
let locked = false;
const nativeFetch = globalThis.fetch.bind(globalThis);
export function recoveryKey(id) {
  const legacy = 'weppt-recovery-' + id;
  if (!account || account.workspace === 'local') return legacy;
  const key = 'weppt-recovery-' + account.workspace + '-' + id;
  if (account.username === 'admin') {
    try { if (!localStorage.getItem(key) && localStorage.getItem(legacy)) { localStorage.setItem(key, localStorage.getItem(legacy)); localStorage.removeItem(legacy); } } catch {}
  }
  return key;
}
function lock() {
  if (locked) return;
  locked = true;
  const panel = document.createElement('div');
  panel.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:white;display:grid;place-content:center;gap:20px;text-align:center;font:18px sans-serif';
  const message = document.createElement('p');
  message.textContent = '登录账号已变化，请刷新后继续。未保存修改仍保留在原账号的恢复记录中。';
  const button = document.createElement('button');
  button.textContent = '刷新页面'; button.onclick = () => location.replace('/');
  panel.append(message, button); document.body.append(panel);
}
export async function initializeAccount() {
  const response = await nativeFetch('/api/session?bootstrap=1', {cache:'no-store'});
  if (!response.ok) { location.replace('/login'); throw Error('请重新登录。'); }
  account = await response.json();
  if (!account.workspace) throw Error('无法确认当前账号。');
  globalThis.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith('/api/')) return nativeFetch(input, init);
    if (locked) throw Error('登录账号已变化，请刷新后继续。');
    const headers = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));
    headers.set('X-WePPT-Workspace', account.workspace);
    const result = await nativeFetch(input, {...init, headers});
    const actual = result.headers.get('X-WePPT-Workspace');
    if (result.status === 401 || (actual && actual !== account.workspace)) { lock(); throw Error('登录账号已变化，请刷新后继续。'); }
    return result;
  };
  const check = async () => {
    if (locked) return;
    try { const r = await nativeFetch('/api/session', {cache:'no-store'}); if (r.status === 401 || (r.ok && (await r.json()).workspace !== account.workspace)) lock(); } catch {}
  };
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void check(); });
  window.addEventListener('focus', check);
  setInterval(check, 15000);
}

export function accountCacheName(base) { return !account || account.username === 'admin' || account.workspace === 'local' ? base : base + '-' + account.workspace; }
