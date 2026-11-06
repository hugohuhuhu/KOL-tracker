"""Optional browser smoke test: requires Playwright and /usr/bin/chromium."""
import sys, tempfile, threading, secrets, json
from pathlib import Path
PROJECT_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT_ROOT))
import app
from playwright.sync_api import sync_playwright, expect
root=PROJECT_ROOT/'test-results';root.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as temp:
 app.DB_PATH=Path(temp)/'browser.sqlite3';app.initialize()
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
 thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 base=f'http://127.0.0.1:{server.server_port}'
 errors=[]
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
   context=browser.new_context(viewport={'width':1440,'height':1080},user_agent='AquaBrowserTest')
   page=context.new_page()
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.on('console',lambda m:errors.append(m.text) if m.type=='error' and 'favicon' not in m.text else None)
   page.goto(base+'/admin')
   expect(page.locator('#auth-title')).to_have_text('建立你的管理中心')
   page.locator('[name=username]').fill('browser-admin')
   page.locator('[name=password]').fill(secrets.token_urlsafe(24))
   page.locator('#auth-submit').click()
   expect(page.locator('#app')).to_be_visible()
   page.screenshot(path=str(root/'dashboard-empty.png'),full_page=True)
   page.locator('.create-referral').first.click()
   page.locator('#referral-form [name=name]').fill('小安的旅行日記')
   page.locator('#referral-form [name=channel]').fill('Instagram')
   page.locator('#referral-form [name=code]').fill('AP-TRAVEL')
   page.locator('#referral-submit').click()
   expect(page.locator('#overview-table')).to_contain_text('小安的旅行日記')
   visitor=browser.new_context(viewport={'width':390,'height':844},user_agent='AquaVisitorTest')
   landing=visitor.new_page()
   landing.on('pageerror',lambda e:errors.append(str(e)))
   landing.goto(base+'/r/AP-TRAVEL')
   expect(landing.locator('#referral-badge')).to_have_text('✳ 夥伴專屬推薦 · AP-TRAVEL')
   expect(landing.locator('.booking-link')).to_have_count(2)
   expect(landing.locator('.social-link')).to_have_count(3)
   landing.screenshot(path=str(root/'landing-mobile.png'),full_page=True)
   assert landing.evaluate('document.documentElement.scrollWidth<=innerWidth'),'mobile landing overflow'
   visitor.route('https://www.kkday.com/**',lambda route:route.fulfill(status=200,body='Booking destination intercepted by local test'))
   with landing.expect_popup() as popup:
    landing.locator('.booking-link.kkday').click()
   popup.value.wait_for_url('https://www.kkday.com/**')
   popup.value.wait_for_load_state()
   assert popup.value.url==app.DEFAULT_LINKS['kkday'],popup.value.url
   page.reload()
   expect(page.locator('#stat-visits')).to_have_text('1')
   expect(page.locator('#stat-clicks')).to_have_text('1')
   expect(page.locator('#stat-unique')).to_have_text('1')
   page.screenshot(path=str(root/'dashboard-desktop.png'),full_page=True)
   page.locator('[data-view=settings]').click()
   expect(page.locator('#settings-form [name=website]')).to_have_value(app.DEFAULT_LINKS['website'])
   page.locator('#settings-form [name=subtitle]').fill('測試更新的樂園簡介')
   page.locator('#settings-form [type=submit]').click()
   expect(page.locator('#toast')).to_contain_text('已同步更新')
   landing.reload();expect(landing.locator('#brand-subtitle')).to_have_text('測試更新的樂園簡介')
   page.locator('[data-view=referrals]').click()
   page.locator('#search').fill('找不到');expect(page.locator('#referral-table')).to_contain_text('找不到符合條件')
   page.locator('#search').fill('小安')
   page.locator('[data-edit]').last.click()
   page.locator('#referral-form [name=active]').uncheck()
   page.locator('#referral-submit').click()
   expect(page.locator('#referral-table .status')).to_have_text('已停用')
   response=landing.goto(base+'/r/AP-TRAVEL');assert response.status==404
   page.set_viewport_size({'width':390,'height':844})
   page.locator('[data-view=overview]').click()
   page.screenshot(path=str(root/'dashboard-mobile.png'),full_page=True)
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'mobile admin overflow'
   page.locator('#logout').click();expect(page.locator('#auth-screen')).to_be_visible()
   browser.close()
  assert not errors,errors
  print(json.dumps({'browser':'system Chromium','passed':['first admin setup','referral creation','mobile landing and five links','KKday redirect attribution','unique visitors','dashboard counts','settings persist to landing','search','disable referral','mobile admin layout','logout'],'screenshots':str(root),'browser_errors':errors},ensure_ascii=False))
 finally:
  server.shutdown();server.server_close();thread.join()
