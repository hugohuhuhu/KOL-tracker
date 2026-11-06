import subprocess, os, time, json, http.client, secrets
from http.cookies import SimpleCookie
prefix=['docker','--host=unix:///var/run/docker.sock']
execution_env=os.environ.copy()
for k in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'): execution_env.pop(k,None)
execution_env['ADMIN_USERNAME']='container-test-admin'
execution_env['ADMIN_PASSWORD']=secrets.token_urlsafe(24)
name='aqua-check-'+secrets.token_hex(4);volume=name+'-data'
def docker(*args):
 return subprocess.check_output(prefix+list(args),env=execution_env,text=True,stderr=subprocess.PIPE).strip()
def start():
 docker('run','-d','--name',name,'-p','127.0.0.1::8765','-v',volume+':/data','-e','PORT=8765','-e','ADMIN_USERNAME','-e','ADMIN_PASSWORD','-e','COOKIE_SECURE=1','aqua-kol-tracker:local')
 return int(json.loads(docker('inspect','--format','{{json .NetworkSettings.Ports}}',name))['8765/tcp'][0]['HostPort'])
def req(path,body=None,cookie='',csrf=''):
 c=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
 c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,{'Content-Type':'application/json','Cookie':cookie,'X-CSRF-Token':csrf,'User-Agent':'ContainerSmokeTest'})
 r=c.getresponse();status=r.status;headers=dict(r.getheaders());raw=r.read();c.close()
 return status,json.loads(raw) if raw and 'json' in headers.get('Content-Type','') else raw,headers
def ready():
 for _ in range(60):
  try:
   if req('/health')[0]==200:return
  except OSError:pass
  time.sleep(.1)
 raise AssertionError('container did not become healthy')
try:
 docker('volume','create',volume)
 port=start();ready()
 credentials={'username':execution_env['ADMIN_USERNAME'],'password':execution_env['ADMIN_PASSWORD']}
 status,body,headers=req('/api/login',credentials);assert status==200
 assert 'Secure' in headers['Set-Cookie']
 cookie=SimpleCookie(headers['Set-Cookie']);cookie='aqua_session='+cookie['aqua_session'].value
 csrf=body['csrf']
 assert req('/api/referrals',{'name':'Persistence smoke test','code':'AP-DOCKER'},cookie,csrf)[0]==201
 assert req('/r/AP-DOCKER')[0]==302
 docker('rm','-f',name)
 port=start();ready()
 assert req('/api/public?code=AP-DOCKER')[0]==200
 status,body,headers=req('/api/login',credentials);assert status==200
 cookie=SimpleCookie(headers['Set-Cookie']);cookie='aqua_session='+cookie['aqua_session'].value
 assert req('/api/dashboard',cookie=cookie)[1]['totals']['visits']==1
 print('Docker PASS: PORT binding, health, bootstrap admin, Secure cookie, referral tracking, volume persistence across container replacement')
finally:
 try:docker('rm','-f',name)
 except subprocess.CalledProcessError:pass
 try:docker('volume','rm',volume)
 except subprocess.CalledProcessError:pass
