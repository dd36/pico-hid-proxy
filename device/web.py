# Minimal async HTTP server for Pico HID Proxy web control
# Serves a public HTML page and a token-authenticated JSON API endpoint.

import json
import uasyncio as asyncio

# Max request body. Macro bodies arrive here, so this must be well above
# the old 1 KB cap or multi-line macros get silently truncated.
_MAX_BODY = 16384

_dispatch_fn = None
_web_password = None
_api_enabled = False
_webui_enabled = False

_HTML = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pico HID Proxy</title>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,sans-serif;max-width:520px;margin:20px auto;padding:0 12px;background:#1a1a2e;color:#e0e0e0}
h2{color:#0ff;margin-bottom:4px}
label{display:block;margin-top:10px;font-size:14px;color:#aaa}
input,button{font-size:15px;padding:8px;width:100%;border:1px solid #333;border-radius:4px;background:#16213e;color:#e0e0e0}
input:focus{outline:none;border-color:#0ff}
button{margin-top:14px;background:#0ff;color:#1a1a2e;font-weight:bold;border:none;cursor:pointer}
button:active{background:#0aa}
#res{margin-top:12px;padding:8px;background:#0d1117;border-radius:4px;min-height:24px;font-family:monospace;white-space:pre-wrap;font-size:14px}
details{margin-top:18px;font-size:13px;color:#888}
summary{cursor:pointer;color:#0ff;font-size:14px}
table{width:100%;border-collapse:collapse;margin-top:6px}
td{padding:3px 6px;border-bottom:1px solid #222;font-family:monospace;font-size:12px}
td:first-child{color:#7ec8e3;white-space:nowrap}
h3{color:#0ff;margin:22px 0 0;font-size:16px;border-top:1px solid #2a2a4a;padding-top:16px}
textarea{font-size:14px;padding:8px;width:100%;border:1px solid #333;border-radius:4px;background:#16213e;color:#e0e0e0;font-family:monospace;resize:vertical}
textarea:focus,select:focus{outline:none;border-color:#0ff}
select{font-size:15px;padding:8px;width:100%;border:1px solid #333;border-radius:4px;background:#16213e;color:#e0e0e0}
.row{display:flex;gap:8px;flex-wrap:wrap}
.row button{flex:1;min-width:80px}
button.warn{background:#ff6b6b;color:#1a1a2e}
button.warn:active{background:#c44}
.chk{display:flex;align-items:center;gap:8px;margin-top:12px;color:#aaa;font-size:14px}
.chk label{margin:0}
input[type=checkbox]{width:16px;height:16px;padding:0;border:none;border-radius:0;background:none;accent-color:#0ff;flex:none}
.hint{margin:8px 0 0;font-size:13px;color:#7a7a8c;line-height:1.45}
button.secondary{background:#2a2a4a;color:#c8c8d8}
button.secondary:active{background:#3a3a5a}
#mstat,#astat{margin-top:10px;padding:6px 8px;background:#0d1117;border-radius:4px;font-family:monospace;font-size:13px;color:#7ec8e3}
</style></head><body>
<h2>Pico HID Proxy</h2>
<label>Command</label>
<input id="cmd" placeholder="e.g. key tap a, key type Hello, mouse move 10 20" autofocus>
<label>Delay (ms)</label>
<input id="delay" type="number" value="0" min="0" step="500">
<label>Token</label>
<input id="token" type="password" placeholder="Set via: api token <value>">
<button onclick="send()">Execute</button>
<div id="res"></div>

<h3>Macros</h3>
<label>Saved macros</label>
<select id="mlist" onchange="mload()"><option value="">-- new macro --</option></select>
<label>Name</label>
<input id="mname" placeholder="gold1">
<label>Steps (one command per line, use <code>sleep &lt;ms&gt;</code> to wait)</label>
<textarea id="mbody" rows="9" spellcheck="false" placeholder="key down w
sleep 800
key up w
mouse move 120 0
sleep 300
key tap space
sleep 5000"></textarea>
<div class="row">
<button onclick="msave()">Save</button>
<button onclick="mrun(false)">Run</button>
<button onclick="mrun(true)">Loop</button>
</div>
<div class="row">
<button class="warn" onclick="mstop()">Stop</button>
<button class="warn" onclick="mdel()">Delete</button>
</div>
<div id="mstat">macro: &mdash;</div>

<h3>Autorun on startup</h3>
<p class="hint">Runs a saved macro every time the Pico powers up, with or without WiFi.
The startup delay is the only window to cancel it &mdash; send <code>macro stop</code>
during the countdown.</p>
<label>Macro to run at boot</label>
<select id="amacro"><option value="">-- none --</option></select>
<label>Delay (ms, minimum 3000)</label>
<input id="adelay" type="number" value="5000" min="3000" step="1000">
<div class="chk"><input type="checkbox" id="aloop"><label for="aloop">Loop forever</label></div>
<div class="row">
<button onclick="aset()">Set autorun</button>
<button class="secondary" onclick="aoff()">Disable</button>
</div>
<div id="astat">autorun: &mdash;</div>

<details><summary>Command Reference</summary><table>
<tr><td colspan="2" style="color:#0ff;font-weight:bold;border:none;padding-top:8px">Keyboard</td></tr>
<tr><td>key tap &lt;name&gt;</td><td>Press &amp; release key</td></tr>
<tr><td>key down &lt;name&gt;</td><td>Hold key down</td></tr>
<tr><td>key up &lt;name&gt;</td><td>Release key</td></tr>
<tr><td>key mod &lt;mods&gt; &lt;key&gt;</td><td>Modifier combo (e.g. key mod ctrl+shift esc)</td></tr>
<tr><td>key type &lt;text&gt;</td><td>Type a string</td></tr>
<tr><td>key release</td><td>Release all held keys</td></tr>
<tr><td colspan="2" style="color:#0ff;font-weight:bold;border:none;padding-top:8px">Mouse</td></tr>
<tr><td>mouse move &lt;dx&gt; &lt;dy&gt;</td><td>Relative mouse move</td></tr>
<tr><td>mouse abs &lt;x&gt; &lt;y&gt;</td><td>Absolute position (0-32767)</td></tr>
<tr><td>mouse click &lt;btn&gt;</td><td>Click left/right/middle</td></tr>
<tr><td>mouse down &lt;btn&gt;</td><td>Hold mouse button</td></tr>
<tr><td>mouse up &lt;btn&gt;</td><td>Release mouse button</td></tr>
<tr><td>mouse scroll &lt;n&gt;</td><td>Scroll wheel (+ up, - down)</td></tr>
<tr><td>mouse release</td><td>Release all held buttons</td></tr>
<tr><td colspan="2" style="color:#0ff;font-weight:bold;border:none;padding-top:8px">Gamepad (pad mode)</td></tr>
<tr><td>pad tap &lt;button&gt;</td><td>Press &amp; release (a/b/x/y/l/r/zl/zr/plus/minus/home/capture)</td></tr>
<tr><td>pad down / up &lt;button&gt;</td><td>Hold / release a button</td></tr>
<tr><td>pad dpad &lt;dir&gt;</td><td>up/upright/right/.../neutral</td></tr>
<tr><td>pad stick &lt;l|r&gt; &lt;x&gt; &lt;y&gt;</td><td>Analog stick, -100..100</td></tr>
<tr><td>pad release</td><td>Release buttons, centre sticks</td></tr>
<tr><td>usb mode &lt;hid|pad&gt;</td><td>Switch USB personality (reboot to apply)</td></tr>
<tr><td>usb status</td><td>Show running / configured USB mode</td></tr>
<tr><td colspan="2" style="color:#0ff;font-weight:bold;border:none;padding-top:8px">Macros</td></tr>
<tr><td>sleep &lt;ms&gt;</td><td>Wait (only valid inside a macro)</td></tr>
<tr><td>repeat &lt;n&gt;</td><td>Start a block that runs n times (macro only)</td></tr>
<tr><td>end</td><td>Close the current repeat block</td></tr>
<tr><td>macro save &lt;name&gt;</td><td>Save; body follows on later lines</td></tr>
<tr><td>macro end / abort</td><td>Finish or cancel serial capture</td></tr>
<tr><td>macro run &lt;name&gt; [loop]</td><td>Run a macro, optionally forever</td></tr>
<tr><td>macro stop</td><td>Stop macro, cancel pending autorun</td></tr>
<tr><td>macro list</td><td>List saved macros</td></tr>
<tr><td>macro show &lt;name&gt;</td><td>Print a macro body</td></tr>
<tr><td>macro delete &lt;name&gt;</td><td>Delete a macro</td></tr>
<tr><td>macro status</td><td>Show what is running</td></tr>
<tr><td>macro autorun &lt;n&gt; &lt;ms&gt; [loop]</td><td>Run &lt;n&gt; &lt;ms&gt; after boot</td></tr>
<tr><td>macro autorun off</td><td>Disable autorun</td></tr>
<tr><td>macro autorun status</td><td>Show autorun setting</td></tr>
<tr><td colspan="2" style="color:#0ff;font-weight:bold;border:none;padding-top:8px">WiFi</td></tr>
<tr><td>wifi set &lt;ssid&gt; &lt;pass&gt;</td><td>Save WiFi credentials</td></tr>
<tr><td>wifi get</td><td>Show saved credentials</td></tr>
<tr><td>wifi connect [ssid] [pass]</td><td>Connect (use saved if no args)</td></tr>
<tr><td>wifi disconnect</td><td>Disconnect WiFi</td></tr>
<tr><td>wifi status</td><td>Show WiFi status</td></tr>
<tr><td>wifi clear</td><td>Delete saved credentials</td></tr>
<tr><td colspan="2" style="color:#0ff;font-weight:bold;border:none;padding-top:8px">API</td></tr>
<tr><td>api token &lt;value&gt;</td><td>Set API token</td></tr>
<tr><td>api enable / disable</td><td>Enable or disable API</td></tr>
<tr><td>api status</td><td>Show API enabled state</td></tr>
<tr><td colspan="2" style="color:#0ff;font-weight:bold;border:none;padding-top:8px">Web UI</td></tr>
<tr><td>webui enable / disable</td><td>Enable or disable web UI</td></tr>
<tr><td>webui status</td><td>Show web UI enabled state</td></tr>
<tr><td colspan="2" style="color:#0ff;font-weight:bold;border:none;padding-top:8px">System</td></tr>
<tr><td>ping</td><td>Connection test</td></tr>
<tr><td>status</td><td>Show system status, free RAM &amp; flash</td></tr>
<tr><td>reboot</td><td>Restart the Pico</td></tr>
<tr><td>reboot bootloader</td><td>Reboot into BOOTSEL mode</td></tr>
</table></details>
<details><summary>API Usage</summary>
<p style="margin:6px 0;font-size:13px">POST to <code>/api</code> with JSON body:</p>
<pre style="background:#0d1117;padding:8px;border-radius:4px;font-size:12px;overflow-x:auto">curl -X POST http://PICO_IP/api \\
  -H "Content-Type: application/json" \\
  -d '{"cmd":"key type Hello","delay":0,"token":"YOUR_TOKEN"}'</pre>
<p style="margin:6px 0;font-size:13px">Response: <code>{"ok":true,"result":"OK"}</code></p>
</details>
<script>
const $ =id=> document.getElementById(id);
window.onload=async()=>{
 $('token').value=localStorage.getItem('hid_token')||'';
 if($('token').value){await mrefresh();await refreshStatus()}
 else{$('mstat').textContent='enter the API token above to load macros'}
};
async function api(cmd){
 const t=$('token').value;localStorage.setItem('hid_token',t);
 try{
  const r=await fetch('/api',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({cmd:cmd,delay:0,token:t})});
  return await r.json();
 }catch(e){return {ok:false,error:e.message}}
}
function show(j){$('res').textContent=j.ok?j.result:('ERROR: '+(j.error||j.result||'request failed'))}
async function refreshStatus(){
 const m=await api('macro status');if(m.ok)$('mstat').textContent=m.result;
 const a=await api('macro autorun status');
 if(!a.ok)return;
 $('astat').textContent=a.result;
 // Reflect what the device actually has set, not what was last typed.
 const hit=a.result.match(/^autorun: '([^']+)' after (\\d+) ms( loop)?/);
 if(hit){
  $('amacro').value=hit[1];
  $('adelay').value=hit[2];
  $('aloop').checked=!!hit[3];
 }else{
  $('amacro').value='';
 }
}
async function mrefresh(){
 const j=await api('macro list');
 const names=(j.ok&&j.result&&j.result.indexOf('no macros')!==0)
  ?j.result.split('\\n').map(n=>n.trim()).filter(n=>n):[];
 fill($('mlist'),names,'-- new macro --');
 fill($('amacro'),names,'-- none --');
}
function fill(sel,names,placeholder){
 const cur=sel.value;
 sel.innerHTML='';
 const p=document.createElement('option');p.value='';p.textContent=placeholder;sel.appendChild(p);
 names.forEach(n=>{const o=document.createElement('option');o.value=n;o.textContent=n;sel.appendChild(o)});
 sel.value=names.indexOf(cur)>=0?cur:'';
}
async function mload(){
 const n=$('mlist').value;
 if(!n){$('mname').value='';$('mbody').value='';return}
 $('mname').value=n;
 const j=await api('macro show '+n);
 if(j.ok){$('mbody').value=j.result}else{show(j)}
}
async function msave(){
 const n=$('mname').value.trim();
 if(!n){show({ok:false,error:'macro name required'});return}
 show(await api('macro save '+n+'\\n'+$('mbody').value));
 await mrefresh();$('mlist').value=n;await refreshStatus();
}
async function mrun(loop){
 const n=$('mname').value.trim();
 if(!n){show({ok:false,error:'macro name required'});return}
 show(await api('macro run '+n+(loop?' loop':'')));
 await refreshStatus();
}
async function mstop(){show(await api('macro stop'));await refreshStatus()}
async function mdel(){
 const n=$('mname').value.trim();if(!n)return;
 if(!confirm('Delete macro "'+n+'"?'))return;
 show(await api('macro delete '+n));
 $('mname').value='';$('mbody').value='';$('mlist').value='';
 await mrefresh();await refreshStatus();
}
async function aset(){
 const n=$('amacro').value;
 if(!n){show({ok:false,error:'pick a macro to run at boot'});return}
 const d=parseInt($('adelay').value)||5000;
 show(await api('macro autorun '+n+' '+d+($('aloop').checked?' loop':'')));
 await refreshStatus();
}
async function aoff(){show(await api('macro autorun off'));await refreshStatus()}
async function send(){
 const t=$('token').value;localStorage.setItem('hid_token',t);
 const cmd=$('cmd').value;
 const isReboot=cmd.trim().toLowerCase().startsWith('reboot');
 $('res').textContent='...';
 try{
  const r=await fetch('/api',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({cmd:cmd,delay:parseInt($('delay').value)||0,token:t})});
  const j=await r.json();
  if(j.ok){$('res').textContent=j.result;$('cmd').value=''}
  else{$('res').textContent='ERROR: '+j.error}
 }catch(e){
  if(isReboot){$('cmd').value=''}
  else{$('res').textContent='ERROR: '+e.message}
 }
 if(isReboot)waitReboot();
}
function waitReboot(){
 const el=$('res');const t0=Date.now();
 el.textContent='Rebooting... waiting for device';
 const iv=setInterval(async()=>{
  if(Date.now()-t0>60000){clearInterval(iv);el.textContent='Reboot timed out (60s)';return}
  try{const r=await fetch('/health');if(r.ok){clearInterval(iv);location.reload()}}catch(e){}
 },2000);
}
$('cmd').onkeydown=e=>{if(e.key==='Enter')send()};
// The token lives in localStorage, which is per-device: a phone opening this
// page for the first time has none, so nothing would load until a reload.
$('token').onchange=async()=>{
 localStorage.setItem('hid_token',$('token').value);
 if($('token').value){await mrefresh();await refreshStatus()}
};
</script></body></html>"""


def start(password, dispatch_fn, api_enabled=False, webui_enabled=False):
    global _dispatch_fn, _web_password, _api_enabled, _webui_enabled
    _dispatch_fn = dispatch_fn
    _web_password = password
    _api_enabled = api_enabled
    _webui_enabled = webui_enabled


def set_password(password):
    global _web_password
    _web_password = password


def set_api_enabled(val):
    global _api_enabled
    _api_enabled = bool(val)


def set_webui_enabled(val):
    global _webui_enabled
    _webui_enabled = bool(val)


def _url_decode(s):
    result = []
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try:
                result.append(chr(int(s[i + 1 : i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        result.append(s[i])
        i += 1
    return "".join(result)


def _send_response(writer, status, content_type, body):
    writer.write(
        "HTTP/1.0 {} OK\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n".format(
            status, content_type, len(body)
        ).encode()
    )
    writer.write(body if isinstance(body, bytes) else body.encode())


async def _handle_client(reader, writer):
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5)
        if not request_line:
            return
        request_line = request_line.decode().strip()
        parts = request_line.split(" ")
        if len(parts) < 2:
            return
        method = parts[0]
        path = parts[1]

        # Read headers
        content_length = 0
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if not line or line == b"\r\n" or line == b"\n":
                break
            decoded = line.decode().strip().lower()
            if decoded.startswith("content-length:"):
                try:
                    content_length = int(decoded.split(":")[1].strip())
                except ValueError:
                    pass

        # GET /health — lightweight health check (no auth required)
        if method == "GET" and path == "/health":
            _send_response(writer, 200, "application/json", '{"ok":true}')
            await writer.drain()
            return

        # GET / — serve HTML page
        if method == "GET" and path == "/":
            if not _webui_enabled:
                _send_response(writer, 404, "text/plain", "not found")
                await writer.drain()
                return
            _send_response(writer, 200, "text/html", _HTML)
            await writer.drain()
            return

        # POST /api — execute command
        if method == "POST" and path == "/api":
            if not _api_enabled:
                _send_response(writer, 404, "text/plain", "not found")
                await writer.drain()
                return

            body = b""
            if content_length > 0:
                remaining = min(content_length, _MAX_BODY)
                chunks = []
                while remaining > 0:
                    chunk = await asyncio.wait_for(
                        reader.read(remaining), timeout=5
                    )
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                body = b"".join(chunks)

            try:
                data = json.loads(body)
            except ValueError:
                _send_response(
                    writer,
                    400,
                    "application/json",
                    '{"ok":false,"error":"invalid json"}',
                )
                await writer.drain()
                return

            token = data.get("token", "")
            if token != _web_password:
                _send_response(
                    writer,
                    403,
                    "application/json",
                    '{"ok":false,"error":"unauthorized"}',
                )
                await writer.drain()
                return

            cmd_str = data.get("cmd", "").strip()
            delay_ms = 0
            try:
                delay_ms = int(data.get("delay", 0))
            except (ValueError, TypeError):
                pass

            if not cmd_str:
                _send_response(
                    writer,
                    400,
                    "application/json",
                    '{"ok":false,"error":"no command"}',
                )
                await writer.drain()
                return

            # Apply delay (milliseconds)
            if delay_ms > 0:
                await asyncio.sleep_ms(delay_ms)

            result = _dispatch_fn(cmd_str) if _dispatch_fn else "ERR no dispatcher"
            resp = json.dumps({"ok": not result.startswith("ERR"), "result": result})
            _send_response(writer, 200, "application/json", resp)
            await writer.drain()
            return

        # 404 for anything else
        _send_response(writer, 404, "text/plain", "not found")
        await writer.drain()

    except Exception:
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def run_server():
    global _server
    _server = await asyncio.start_server(_handle_client, "0.0.0.0", 80)
    # Keep this task alive so _server isn't garbage collected
    while True:
        await asyncio.sleep(60)
