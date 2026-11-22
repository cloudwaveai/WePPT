import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {existsSync} from 'node:fs';
test('release retains logout, confirmed deletion and account-isolated recovery',async()=>{
 const html=await readFile(new URL('../public/index.html',import.meta.url),'utf8');
 const app=await readFile(new URL('../public/app.js',import.meta.url),'utf8');
 assert.match(html,/id="logout"/);
 assert.match(app,/data-delete-project/);assert.match(app,/confirmDeleteProject/);
 if(existsSync(new URL('../public/account-session.js',import.meta.url))){
  assert.match(html,/account-bootstrap/);
  assert.match(app,/localStorage.removeItem\(recoveryKey\(project.id\)\)/);
 }
});
