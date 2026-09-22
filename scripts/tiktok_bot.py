from __future__ import annotations
import asyncio, importlib, json, os, shutil, subprocess, sys
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    sys.stderr.reconfigure(encoding="utf-8",errors="replace")
except Exception: pass

IS_FROZEN=bool(getattr(sys,"frozen",False))
BASE=Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
CONFIG_FILE=BASE/"tiktok_config.json"
if CONFIG_FILE.exists():
    try:
        _config=json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(_config,dict):
            for _key,_value in _config.items():
                if isinstance(_key,str) and _value is not None:
                    os.environ.setdefault(_key,str(_value))
    except (OSError,ValueError,TypeError):
        pass

_frozen_root=Path(getattr(sys,"_MEIPASS",str(BASE)))
_user_root=Path(os.getenv("LOCALAPPDATA",str(Path.home())))/"SmartMerchantTikTok"
if IS_FROZEN:
    LTTK=Path(os.getenv("TIKTOK_LTTK_DIR",str(_user_root/"lttk"))).resolve()
    _bundled_lttk=_frozen_root/"lttk"
    if _bundled_lttk.is_dir() and not LTTK.exists():
        LTTK.parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(_bundled_lttk,LTTK)
    RUNTIME=Path(os.getenv("TIKTOK_RUNTIME_DIR",str(_user_root/"data-runtime"))).resolve()
else:
    LTTK=Path(os.getenv("TIKTOK_LTTK_DIR",str(BASE/"lttk"))).resolve()
    RUNTIME=Path(os.getenv("TIKTOK_RUNTIME_DIR",str(BASE/"data-runtime"))).resolve()
COOKIE=Path(os.getenv("TIKTOK_COOKIE_FILE",str(RUNTIME/"tiktok_cookies.json"))).resolve()
BROWSER=os.getenv("TIKTOK_BROWSER","").strip().lower()
PLUGIN=LTTK/"plugins"/"smart_merchant_bridge.py"
SESSION=LTTK/"sesion"
REPO="https://github.com/Linkmail16/ReLttk-TikTok-Client-Bot.git"

BROWSER_IMPORT_CODE=r'''
import importlib, os
from pathlib import Path

pkg=Path.cwd().name
browser=os.environ.get("TIKTOK_BROWSER", "chrome").lower()
bc=importlib.import_module(pkg+".browsercookies")
qr=importlib.import_module(pkg+".qrlogin")

roots={
    "chrome": Path(os.environ.get("LOCALAPPDATA", ""))/"Google/Chrome/User Data",
    "edge": Path(os.environ.get("LOCALAPPDATA", ""))/"Microsoft/Edge/User Data",
    "brave": Path(os.environ.get("LOCALAPPDATA", ""))/"BraveSoftware/Brave-Browser/User Data",
}
root=roots.get(browser)
profiles=[]
selected=os.environ.get("TIKTOK_BROWSER_PROFILE", "").strip()
if selected:
    profiles=[selected]
elif root and root.exists():
    profiles=["Default"]+sorted(p.name for p in root.glob("Profile *") if p.is_dir())

if browser == "firefox":
    cookies=bc.get_tiktok_cookies(browser)
    qr._write_cookies(cookies)
    print("[browser] imported firefox cookies")
    raise SystemExit(0)

for profile in profiles:
    cookie_path=root/profile/"Network"/"Cookies"
    if not cookie_path.exists():
        continue
    bc._CHROMIUM_PATHS[browser]=str(cookie_path)
    try:
        cookies=bc.get_tiktok_cookies(browser)
    except Exception as exc:
        print(f"[browser] {profile}: {exc}")
        continue
    qr._write_cookies(cookies)
    print(f"[browser] imported {browser}/{profile} cookies")
    raise SystemExit(0)

print(f"[browser] no sessionid found in {browser} profiles")
raise SystemExit(1)
'''

SESSION_CHECK_CODE=r'''
import urllib.request
from lttk.qrlogin import load_session

cookies=load_session("_temp")
if not cookies.get("sessionid"):
    print("[session] missing sessionid")
    raise SystemExit(1)
cookie="; ".join(f"{k}={v}" for k,v in cookies.items())
req=urllib.request.Request(
    "https://www.tiktok.com/messages?lang=es-419",
    headers={"User-Agent":"Mozilla/5.0", "Cookie":cookie},
)
with urllib.request.urlopen(req, timeout=15) as response:
    final_url=response.geturl()
if "/login" in final_url:
    print("[session] TikTok redirected to login; cookie expired or invalid")
    raise SystemExit(1)
print("[session] TikTok session valid")
'''

# The ReLttk process owns the live websocket session, so the API cannot send
# a TikTok DM directly.  A tiny localhost control endpoint lets the CRM ask
# this already-authenticated process to send on a specific conversation.
CONTROL_CODE=r'''
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import hmac as _hmac

CONTROL_SERVER=None
CONTROL_LOOP=None
CONTROL_BOT=None

class _TikTokControlHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _reply(self, status, payload):
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.rstrip("/") != "/send":
            self._reply(404, {"detail":"TikTok bridge route not found"})
            return
        provided=self.headers.get("X-TikTok-Bridge-Secret", "")
        if not BRIDGE_SECRET or not _hmac.compare_digest(str(provided), str(BRIDGE_SECRET)):
            self._reply(401, {"detail":"TikTok bridge secret không đúng"})
            return
        try:
            length=int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1024 * 1024:
                raise ValueError("Payload TikTok không hợp lệ")
            payload=json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Payload TikTok không hợp lệ")
            conv=str(payload.get("threadId") or payload.get("conv_id") or "").strip()
            message=str(payload.get("message") or payload.get("text") or "").strip()
            if not conv or not message:
                raise ValueError("Thiếu threadId hoặc message")
            if CONTROL_BOT is None or CONTROL_LOOP is None:
                self._reply(503, {"detail":"TikTok bridge chưa sẵn sàng"})
                return
            future=asyncio.run_coroutine_threadsafe(
                CONTROL_BOT.send_message(conv_id=conv, text=message),
                CONTROL_LOOP,
            )
            result=future.result(timeout=30)
            client_id=None
            if isinstance(result, (tuple, list)) and len(result) > 1:
                client_id=result[1]
            elif result is not None:
                client_id=result
            self._reply(200, {
                "status":"sent",
                "message_id":"tiktok-bridge:" + s(client_id or time.time_ns()),
                "threadId":conv,
            })
        except ValueError as exc:
            self._reply(400, {"detail":str(exc)})
        except Exception as exc:
            log("❌ TikTok outbound control: "+type(exc).__name__+": "+s(exc))
            self._reply(502, {"detail":"Không thể gửi tin TikTok qua bridge"})

def start_control_server(bot):
    global CONTROL_SERVER, CONTROL_LOOP, CONTROL_BOT
    CONTROL_LOOP=asyncio.get_running_loop()
    CONTROL_BOT=bot
    if CONTROL_SERVER is not None:
        return
    host=os.getenv("TIKTOK_BRIDGE_CONTROL_HOST", "127.0.0.1")
    try:
        port=int(os.getenv("TIKTOK_BRIDGE_CONTROL_PORT", "8091"))
        CONTROL_SERVER=ThreadingHTTPServer((host, port), _TikTokControlHandler)
        CONTROL_SERVER.daemon_threads=True
        Thread(target=CONTROL_SERVER.serve_forever, daemon=True).start()
        log(f"🎛 TikTok outbound bridge: http://{host}:{port}/send")
    except Exception as exc:
        CONTROL_SERVER=None
        log("⚠️ Không mở được TikTok outbound bridge: "+type(exc).__name__+": "+s(exc))
'''

# Normalize TikTok's non-text events before they reach the CRM.  ReLttk
# exposes sticker URLs and video/photo IDs, while the exact playable URL is
# optional because TikTok may reject a detail lookup for an expired share.
TIKTOK_MEDIA_CODE=r'''
async def resolve_tiktok_media(bot, msg):
    try:
        awe = int(msg.get("awe_type") or 0)
    except (TypeError, ValueError):
        awe = 0
    media_type = ""
    media_url = ""
    external_id = ""
    metadata = {"awe_type": awe}
    summary = ""

    if awe == 1805:
        media_type = "sticker"
        external_id = s(msg.get("sticker_id") or "").strip()
        media_url = s(msg.get("sticker_url") or msg.get("comment_sticker_url") or "").strip()
        summary = "Khách gửi một sticker trên TikTok."
    elif awe in (800, 810):
        media_type = "video" if awe == 800 else "image"
        external_id = s(msg.get("video_id") or "").strip()
        creator = s(msg.get("video_creator") or "").strip()
        if external_id:
            metadata["video_id"] = external_id
            try:
                detail = await bot.get_item(external_id)
                item = detail.get("itemInfo", {}).get("itemStruct", detail) if isinstance(detail, dict) else {}
                video = item.get("video") if isinstance(item, dict) else {}
                if isinstance(video, dict):
                    if media_type == "video":
                        media_url = s(video.get("playAddr") or video.get("downloadAddr") or "").strip()
                    else:
                        media_url = s(video.get("cover") or video.get("originCover") or video.get("dynamicCover") or "").strip()
            except Exception as exc:
                log(f"⚠️ TikTok media lookup: {type(exc).__name__}")
        summary = "Khách gửi một video trên TikTok." if media_type == "video" else "Khách gửi một hình ảnh trên TikTok."
    elif awe == 1813:
        media_type = "audio"
        external_id = s(msg.get("voice_id") or "").strip()
        summary = "Khách gửi một tin nhắn thoại trên TikTok."
    elif awe == 22:
        media_type = "file"
        external_id = s(msg.get("music_id") or "").strip()
        summary = "Khách gửi một nội dung nhạc trên TikTok."
    elif awe == 1814:
        media_type = "sticker"
        summary = "Khách gửi một thiệp trên TikTok."
    elif awe == 1021:
        media_type = "file"
        summary = "Khách chia sẻ một livestream TikTok."
    elif awe == 1025:
        media_type = "file"
        summary = "Khách chia sẻ một story TikTok."
    elif awe == 1823:
        media_type = "file"
        summary = "Khách gửi một sự kiện cuộc gọi TikTok."

    attachments = []
    # Only persist a browser attachment when a real provider URL is available.
    # An ID without a URL still reaches the CRM as media_type and gets a safe
    # icon/description instead of a broken image or player.
    if media_type and media_url:
        attachments.append({
            "media_type": media_type,
            "url": media_url or None,
            "external_attachment_id": external_id or None,
            "metadata": metadata,
        })
    return media_type, media_url, summary, attachments
'''

PLUGIN_CODE='# -*- coding: utf-8 -*-\nimport asyncio, json, os, time, traceback\nfrom urllib import request as UREQ\nfrom urllib import error as UERR\n\nBACKEND=(os.getenv("SALONDESK_APP_URL") or os.getenv("NEXT_PUBLIC_APP_URL") or "http://127.0.0.1:3000").rstrip("/")\nENDPOINT=os.getenv("TIKTOK_BACKEND_ENDPOINT","/api/channels/tiktok/incoming")\nECHO=os.getenv("TIKTOK_ECHO_TEST","0")=="1"\nDEBUG=os.getenv("TIKTOK_DEBUG_RAW_EVENT","0")=="1"\nAUTO_REPLY=os.getenv("TIKTOK_AUTO_REPLY","0")=="1"\nseen={}\n\ndef log(x=""): print(x,flush=True)\ndef s(x): return "" if x is None else str(x)\n\ndef key(m):\n    return s(m.get("msg_id")) or "|".join([s(m.get("conv_id")),s(m.get("sender_id")),s(m.get("awe_type")),s(m.get("text"))])\n\ndef cleanup():\n    now=time.monotonic()\n    for k,t in list(seen.items()):\n        if now-t>3600: seen.pop(k,None)\n\ndef post(payload):\n    url=BACKEND+ENDPOINT\n    try:\n        req=UREQ.Request(url,data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),\n            headers={"Content-Type":"application/json; charset=utf-8","Accept":"application/json"},method="POST")\n        with UREQ.urlopen(req,timeout=30) as r:\n            raw=r.read().decode("utf-8","replace")\n            d=json.loads(raw)\n            reply=d.get("response") or d.get("reply") or d.get("message") or d.get("text")\n            if isinstance(reply,dict):\n                reply=reply.get("text") or reply.get("content") or reply.get("message")\n            return (s(reply).strip(),None) if reply else (None,"Backend không có response/reply/message/text")\n    except UERR.HTTPError as e:\n        try: body=e.read().decode("utf-8","replace")\n        except: body=""\n        return None,f"HTTP {e.code}: {body[:300]}"\n    except Exception as e:\n        return None,f"{type(e).__name__}: {e}"\n\nasync def backend(payload):\n    return await asyncio.get_running_loop().run_in_executor(None,post,payload)\n\nasync def on_start(bot):\n    log("\\n"+"="*72)\n    log("🟢 TIKTOK REALTIME EVENT LISTENER READY")\n    log("📡 Hook: on_message(bot, msg)")\n    log("🧪 Echo: "+("ON" if ECHO else "OFF"))\n    log("🤖 Auto reply: "+("ON" if AUTO_REPLY else "OFF"))\n    log("🌐 Backend: "+BACKEND+ENDPOINT)\n    log("👉 Dùng ACCOUNT KHÁC gửi DM vào account bot.")\n    log("="*72+"\\n")\n\nasync def on_message(bot,msg):\n    try:\n        if not isinstance(msg,dict):\n            log("⚠️ Event lạ: "+repr(msg)); return\n        cleanup()\n        k=key(msg)\n        if k in seen: return\n        seen[k]=time.monotonic()\n\n        sender=s(msg.get("sender_id")).strip()\n        conv=s(msg.get("conv_id")).strip()\n\n        # Some realtime packets from TikTok are partially decoded by ReLttk:\n        # sender/conv are correct but text/msg_id are empty and awe_type is actually\n        # a large ID. Recover the newest matching message through ReLttk history.\n        if conv and (not s(msg.get("text")).strip() or not s(msg.get("msg_id")).strip()):\n            try:\n                await asyncio.sleep(0.35)\n                hist=await bot.fetch_history(conv,count=8)\n                if isinstance(hist,list):\n                    candidates=[x for x in hist if isinstance(x,dict) and s(x.get("sender_id")).strip()==sender]\n                    candidates=[x for x in candidates if s(x.get("text")).strip()]\n                    if candidates:\n                        best=candidates[0]\n                        # Prefer a candidate with a real message id.\n                        for x in candidates:\n                            if s(x.get("msg_id")).strip():\n                                best=x\n                                break\n                        for fld in ("text","msg_id","msg_type","awe_type","sec_uid","is_group","proto"):\n                            if best.get(fld) not in (None,"",[],{}):\n                                msg[fld]=best[fld]\n                        log("🛟 Recovered text/msg_id from conversation history")\n            except Exception as e:\n                log(f"⚠️ History recovery: {type(e).__name__}: {e}")\n\n        mid=s(msg.get("msg_id")).strip()\n        text=s(msg.get("text")).strip()\n        awe=msg.get("awe_type")\n        own=s(getattr(bot,"_own_user_id","")).strip()\n        if own and sender==own: return\n\n        name=sender or "Unknown"; username=""\n        if sender:\n            try:\n                p=await bot.get_user(sender)\n                if isinstance(p,dict):\n                    username=s(p.get("unique_id") or p.get("username")).strip()\n                    name=s(p.get("nick_name") or p.get("nickname") or username or sender).strip()\n            except Exception as e:\n                log(f"⚠️ get_user: {e}")\n\n        log("\\n"+"="*72)\n        log("📩 TIKTOK INCOMING MESSAGE EVENT")\n        log(f"👤 Tên        : {name}")\n        if username: log(f"🔖 Username   : @{username}")\n        log(f"🆔 User ID    : {sender or \'(none)\'}")\n        log(f"💬 Thread ID  : {conv or \'(none)\'}")\n        log(f"🔑 Message ID : {mid or \'(none)\'}")\n        log(f"📦 awe_type   : {awe}")\n        log(f"📝 Nội dung   : {text or \'(event không có text)\'}")\n        log("="*72)\n        if DEBUG:\n            log("🧪 RAW/FINAL EVENT:")\n            log(json.dumps(msg,ensure_ascii=False,indent=2,default=str))\n\n        effective=text or f"[TikTok event awe_type={awe}]"\n        if ECHO:\n            log("✅ Đã nhận tin nhắn. Auto reply đang TẮT.")\n            return\n\n        log("🌐 POST "+BACKEND+ENDPOINT)\n        reply,err=await backend({\n            "authorId":sender,"threadId":conv,"messageId":mid,"message":effective,\n            "displayName":name,"username":username,"channel":"tiktok",\n            "isGroup":bool(msg.get("is_group",False)),"aweType":awe\n        })\n        if err:\n            log("❌ Backend: "+err)\n            return\n\n        log("🤖 AI response: "+reply)\n\n        if not AUTO_REPLY:\n            log("🚫 Không gửi reply về TikTok vì TIKTOK_AUTO_REPLY=0")\n            return\n\n        try:\n            await bot.send_message(text=reply,msg=msg)\n            log("✅ Đã gửi TikTok reply: "+reply)\n        except Exception as e:\n            log(f"❌ send_message: {type(e).__name__}: {e}")\n            traceback.print_exc()\n    except Exception as e:\n        log(f"❌ on_message CRASH: {type(e).__name__}: {e}")\n        traceback.print_exc()\n\nasync def on_reaction(bot,rxn):\n    log("❤️ TIKTOK REACTION EVENT: "+s(rxn))\n\nasync def on_delete(bot,deleted):\n    log("🗑️ TIKTOK DELETE EVENT: "+s(deleted))\n'
RECONNECT_OLD='                    startup_tasks = []\n                    for name, plugin in list(self._plugins.items()):\n                        if hasattr(plugin, "on_start"):\n                            startup_tasks.append(asyncio.create_task(plugin.on_start(self)))\n                    tasks = [\n                        asyncio.create_task(self._heartbeat()),\n                        asyncio.create_task(self._receiver()),\n                        asyncio.create_task(self._watch_plugins()),\n                        asyncio.create_task(self._stranger_loop()),\n                        *([asyncio.create_task(self._console())] if not self._managed else []),\n                        *startup_tasks,\n                    ]'
RECONNECT_NEW='                    for name, plugin in list(self._plugins.items()):\n                        if hasattr(plugin, "on_start"):\n                            try:\n                                await plugin.on_start(self)\n                            except Exception as e:\n                                _log.error("lttk", f"error en plugin {name} (start): {e}")\n                    tasks = [\n                        asyncio.create_task(self._heartbeat()),\n                        asyncio.create_task(self._receiver()),\n                        asyncio.create_task(self._watch_plugins()),\n                        asyncio.create_task(self._stranger_loop()),\n                        *([asyncio.create_task(self._console())] if not self._managed else []),\n                    ]'
QUOTE_OLD='            if quote is None:\n                quote = {\n                    "text":     msg["text"],\n                    "uid":      msg["sender_id"],\n                    "sec_uid":  msg["sec_uid"],\n                    "awe_type": msg["awe_type"],\n                    "msg_id":   msg["msg_id"],\n                    "msg_type": msg["msg_type"],\n                }'
QUOTE_NEW='            if quote is None:\n                raw_msg_id = str(msg.get("msg_id") or "").strip()\n                if raw_msg_id.isdigit():\n                    quote = {\n                        "text":     msg.get("text", ""),\n                        "uid":      msg.get("sender_id", ""),\n                        "sec_uid":  msg.get("sec_uid", ""),\n                        "awe_type": msg.get("awe_type", 0),\n                        "msg_id":   raw_msg_id,\n                        "msg_type": msg.get("msg_type", 0),\n                    }\n                else:\n                    quote = None'
CLOSE_OLD='            except websockets.exceptions.ConnectionClosed:\n                _log.warn("lttk", "conexion cerrada")\n                break'
CLOSE_NEW='            except websockets.exceptions.ConnectionClosed as e:\n                _log.warn("lttk", f"conexion cerrada (code={getattr(e, \'code\', None)}, reason={getattr(e, \'reason\', \'\')})")\n                break'
HASHLIB_IMPORT_OLD="import json\n"
HASHLIB_IMPORT_NEW="import hashlib\nimport json\n"

def log(x=""): print(x,flush=True)
def run(args,cwd=None,check=True,env=None):
    log("▶ "+subprocess.list2cmdline([str(x) for x in args]))
    r=subprocess.run([str(x) for x in args],cwd=str(cwd) if cwd else None,env=env)
    if check and r.returncode: raise SystemExit(r.returncode)
    return r.returncode

def ensure_lttk():
    if (LTTK/"main.py").exists():
        log("✅ ReLttk OK"); return
    if not shutil.which("git"): raise SystemExit("❌ Không tìm thấy git trong PATH")
    log("📦 Clone ReLttk...")
    run(["git","clone",REPO,str(LTTK)],BASE)
    req=LTTK/"requirements.txt"
    if req.exists(): run([sys.executable,"-m","pip","install","-r",str(req)],LTTK)

def patch_client():
    p=LTTK/"client.py"
    s=p.read_text(encoding="utf-8")
    before=s
    if RECONNECT_OLD in s:
        s=s.replace(RECONNECT_OLD,RECONNECT_NEW,1); log("🔧 Fix reconnect loop")
    if QUOTE_OLD in s:
        s=s.replace(QUOTE_OLD,QUOTE_NEW,1); log("🔧 Fix reply msg_id rỗng")
    if CLOSE_OLD in s:
        s=s.replace(CLOSE_OLD,CLOSE_NEW,1); log("🔧 Thêm mã lỗi websocket")
    compile(s,str(p),"exec")
    if s!=before:
        bak=p.with_suffix(".py.smartmerchant.bak")
        if not bak.exists(): shutil.copy2(p,bak)
        p.write_text(s,encoding="utf-8")
    log("✅ client.py OK")

def patch_api():
    p=LTTK/"core"/"api.py"
    if not p.exists():
        return
    s=p.read_text(encoding="utf-8")
    if "import hashlib\n" not in s:
        s=s.replace(HASHLIB_IMPORT_OLD,HASHLIB_IMPORT_NEW,1)
        compile(s,str(p),"exec")
        p.write_text(s,encoding="utf-8")
        log("🔧 Fix thiếu hashlib trong core/api.py")

def install_plugin():
    PLUGIN.parent.mkdir(parents=True,exist_ok=True)
    # Keep the imported bridge compatible with this CRM's tenant-scoped API.
    # The source plugin is embedded above so ReLttk can still run standalone.
    code=PLUGIN_CODE
    code=code.replace(
        'BACKEND=(os.getenv("SALONDESK_APP_URL") or os.getenv("NEXT_PUBLIC_APP_URL") or "http://127.0.0.1:3000").rstrip("/")',
        'BACKEND=(os.getenv("TIKTOK_BACKEND_URL") or os.getenv("SALONDESK_APP_URL") or os.getenv("NEXT_PUBLIC_APP_URL") or "http://127.0.0.1:8000").rstrip("/")\nSHOP_SLUG=os.getenv("TIKTOK_SHOP_SLUG","").strip()\nBRIDGE_SECRET=os.getenv("TIKTOK_BRIDGE_SECRET","").strip()',
    )
    code=code.replace(
        'headers={"Content-Type":"application/json; charset=utf-8","Accept":"application/json"}',
        'headers={"Content-Type":"application/json; charset=utf-8","Accept":"application/json","X-TikTok-Shop-Slug":SHOP_SLUG,"X-TikTok-Bridge-Secret":BRIDGE_SECRET}',
    )
    code=code.replace(
        'return (s(reply).strip(),None) if reply else (None,"Backend không có response/reply/message/text")',
        'return (s(reply).strip(),None) if reply else (None,None)',
    )
    code=code.replace('seen={}\n', CONTROL_CODE+'\nseen={}\n', 1)
    code=code.replace(
        'async def on_start(bot):\n',
        'async def on_start(bot):\n    start_control_server(bot)\n',
        1,
    )
    code=code.replace(
        '        log("🤖 AI response: "+reply)\n\n        if not AUTO_REPLY:',
        '        if reply:\n            log("🤖 AI response: "+reply)\n        else:\n            log("✅ Backend đã lưu tin TikTok.")\n\n        if not AUTO_REPLY or not reply:',
    )
    # Forward the profile photo returned by ReLttk when available. TikTok
    # does not guarantee this field, so the CRM keeps initials as fallback.
    code=code.replace(
        '        name=sender or "Unknown"; username=""\n',
        '        name=sender or "Unknown"; username=""; avatar_url=profile_avatar(msg.get("avatar_url") or msg.get("avatar_larger") or msg.get("avatar_medium") or msg.get("avatar_thumb") or "")\n',
        1,
    )
    code=code.replace(
        'async def on_start(bot):\n',
        'def profile_avatar(value):\n'
        '    if isinstance(value, str):\n        value=value.strip()\n        return value if value.startswith(("https://", "http://")) else ""\n'
        '    if isinstance(value, dict):\n'
        '        for key in ("url_list", "url", "uri"):\n            found=profile_avatar(value.get(key))\n            if found: return found\n'
        '        for nested in value.values():\n            found=profile_avatar(nested)\n            if found: return found\n'
        '    if isinstance(value, list):\n'
        '        for item in value:\n            found=profile_avatar(item)\n            if found: return found\n'
        '    return ""\n\n'
        'async def on_start(bot):\n',
        1,
    )
    code=code.replace(
        '                    username=s(p.get("unique_id") or p.get("username")).strip()\n',
        '                    username=s(p.get("unique_id") or p.get("username")).strip()\n',
        1,
    )
    code=code.replace(
        '                    name=s(p.get("nick_name") or p.get("nickname") or username or sender).strip()\n'
        '            except Exception as e:\n',
        '                    name=s(p.get("nick_name") or p.get("nickname") or username or sender).strip()\n'
        '                    avatar_url=profile_avatar(p.get("avatar_url") or p.get("avatar") or p.get("avatar_larger") or p.get("avatar_medium") or p.get("avatar_thumb") or p.get("avatars"))\n'
        '                else:\n'
        '                    username=s(getattr(p,"unique_id",None) or getattr(p,"username",None)).strip()\n'
        '                    name=s(getattr(p,"nick_name",None) or getattr(p,"nickname",None) or username or sender).strip()\n'
        '                    avatar_url=profile_avatar(getattr(p,"avatar_url",None) or getattr(p,"avatar_larger",None) or getattr(p,"avatar_medium",None) or getattr(p,"avatar_thumb",None) or getattr(p,"avatar",None) or getattr(p,"avatars",None))\n'
        '            except Exception as e:\n',
        1,
    )
    code=code.replace(
        '            except Exception as e:\n                log(f"⚠️ get_user: {e}")\n',
        '            except Exception as e:\n                log(f"⚠️ get_user: {e}")\n\n'
        '        if not avatar_url.startswith(("https://", "http://")):\n            avatar_url=""\n',
        1,
    )
    code=code.replace(
        '        if username: log(f"🔖 Username   : @{username}")\n',
        '        if username: log(f"🔖 Username   : @{username}")\n'
        '        log(f"🖼 Avatar URL : {avatar_url or \'(none)\'}")\n',
        1,
    )
    code=code.replace(
        '                        for fld in ("text","msg_id","msg_type","awe_type","sec_uid","is_group","proto"):',
        '                        for fld in ("text","msg_id","msg_type","awe_type","sec_uid","is_group","proto","video_id","video_creator","sticker_id","sticker_url","voice_id","music_id","avatar_url","avatar_larger","avatar_medium","avatar_thumb"):',
        1,
    )
    code=code.replace(
        '            "displayName":name,"username":username,"channel":"tiktok",',
        '            "displayName":name,"username":username,"avatarUrl":avatar_url,"channel":"tiktok",',
        1,
    )
    code=code.replace(
        '            "displayName":name,"username":username,"avatarUrl":avatar_url,"channel":"tiktok",',
        '            "displayName":name,"username":username,"avatarUrl":avatar_url,"mediaType":media_type,"mediaUrl":media_url,"attachments":media_attachments,"channel":"tiktok",',
        1,
    )
    code=code.replace(
        'async def on_message(bot,msg):\n',
        TIKTOK_MEDIA_CODE + '\nasync def on_message(bot,msg):\n',
        1,
    )
    code=code.replace(
        '        effective=text or f"[TikTok event awe_type={awe}]"\n',
        '        media_type, media_url, media_text, media_attachments = await resolve_tiktok_media(bot, msg)\n'
        '        effective=text or media_text or "[Khách gửi nội dung TikTok]"\n',
        1,
    )
    compile(code,str(PLUGIN),"exec")
    PLUGIN.write_text(code,encoding="utf-8")
    log("✅ TikTok realtime bridge OK")

def sessions():
    return list(SESSION.glob("*.json")) if SESSION.exists() else []

def _cookie_file_is_usable():
    try:
        data=json.loads(COOKIE.read_text(encoding="utf-8"))
        if isinstance(data,list):
            return any(c.get("name")=="sessionid" and c.get("value") for c in data if isinstance(c,dict))
        return bool(data.get("sessionid")) if isinstance(data,dict) else False
    except (OSError,ValueError,TypeError):
        return False

def _save_imported_cookie():
    source=SESSION/"_temp.json"
    if not source.exists():
        return False
    try:
        data=json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data,dict) or not data.get("sessionid"):
            return False
        COOKIE.parent.mkdir(parents=True,exist_ok=True)
        COOKIE.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        log(f"🍪 Đã tạo cookie mới: {COOKIE}")
        return True
    except (OSError,ValueError,TypeError) as e:
        log(f"⚠️ Không lưu được tiktok_cookies.json: {e}")
        return False

def _import_cookie_file():
    if not COOKIE.exists() or not _cookie_file_is_usable():
        return False
    log(f"🍪 Import cookie: {COOKIE}")
    if IS_FROZEN:
        try:
            data=json.loads(COOKIE.read_text(encoding="utf-8"))
            cookies={item["name"]:item["value"] for item in data if isinstance(item,dict) and item.get("name") and item.get("value")} if isinstance(data,list) else data
            _lttk_module("qrlogin")._write_cookies(cookies)
            return True
        except (OSError,ValueError,TypeError,AttributeError) as exc:
            log(f"⚠️ Không nạp được cookie: {type(exc).__name__}")
            return False
    return run([sys.executable,"main.py","cookies",str(COOKIE)],LTTK,check=False)==0

def _lttk_module(name):
    parent=str(LTTK.parent)
    if parent not in sys.path:
        sys.path.insert(0,parent)
    return importlib.import_module(f"{LTTK.name}.{name}")

def _import_browser_cookie():
    supported={"chrome","edge","brave","firefox"}
    browsers=[BROWSER] if BROWSER else ["chrome","edge","brave","firefox"]
    if any(browser not in supported for browser in browsers):
        log(f"⚠️ TIKTOK_BROWSER không hợp lệ: {BROWSER}. Dùng chrome/edge/brave/firefox.")
        return False
    child_env=os.environ.copy()
    child_env["PYTHONPATH"]=str(LTTK.parent)+(os.pathsep+child_env["PYTHONPATH"] if child_env.get("PYTHONPATH") else "")
    for browser in browsers:
        log(f"🌐 Lấy phiên TikTok trực tiếp từ {browser}; không dùng QR/2FA.")
        if IS_FROZEN:
            try:
                bc=_lttk_module("browsercookies")
                qr=_lttk_module("qrlogin")
                cookies=bc.get_tiktok_cookies(browser)
                qr._write_cookies(cookies)
                if _save_imported_cookie():
                    return True
            except Exception as exc:
                log(f"[browser] {browser}: {exc}")
            continue
        child_env["TIKTOK_BROWSER"]=browser
        ok=run([sys.executable,"-c",BROWSER_IMPORT_CODE],LTTK,check=False,env=child_env)==0
        if ok and _save_imported_cookie():
            return True
    log("ℹ️ Không đọc được cookie trình duyệt. Nếu Chrome/Edge bật mã hóa App-Bound, hãy dùng tiktok_cookies.json xuất thủ công.")
    return False

def verify_session():
    if IS_FROZEN:
        try:
            import urllib.request
            cookies=_lttk_module("qrlogin").load_session("_temp")
            if not cookies.get("sessionid"):
                log("[session] missing sessionid")
                return False
            cookie="; ".join(f"{key}={value}" for key,value in cookies.items())
            request=urllib.request.Request(
                "https://www.tiktok.com/messages?lang=es-419",
                headers={"User-Agent":"Mozilla/5.0","Cookie":cookie},
            )
            with urllib.request.urlopen(request,timeout=15) as response:
                if "/login" in response.geturl():
                    log("[session] TikTok redirected to login; cookie expired or invalid")
                    return False
            log("[session] TikTok session valid")
            return True
        except Exception as exc:
            log(f"[session] {type(exc).__name__}: {exc}")
            return False
    child_env=os.environ.copy()
    child_env["PYTHONPATH"]=str(LTTK.parent)+(os.pathsep+child_env["PYTHONPATH"] if child_env.get("PYTHONPATH") else "")
    return run([sys.executable,"-c",SESSION_CHECK_CODE],LTTK,check=False,env=child_env)==0

def ensure_session():
    if _import_cookie_file():
        log("✅ Đã nạp lại session từ tiktok_cookies.json.")
        return True
    ss=sessions()
    if ss:
        log("✅ Session: "+ss[0].name)
        return True
    if _import_browser_cookie():
        log("✅ Đã sẵn sàng phiên TikTok từ cookie.")
        return True
    log("⚠️ Chưa lấy được phiên TikTok. Hãy đăng nhập TikTok trên trình duyệt, đóng trình duyệt rồi chạy lại.")
    return False

def main():
    RUNTIME.mkdir(parents=True,exist_ok=True)
    log("="*72)
    log("🚀 SMART MERCHANT - ONE FILE TIKTOK BOT")
    log("="*72)
    ensure_lttk()
    patch_api()
    patch_client()
    install_plugin()
    if "--import-browser-cookie" in sys.argv:
        raise SystemExit(0 if _import_browser_cookie() else 1)
    if not ensure_session():
        log("❌ Dừng bot để không rơi vào vòng QR/2FA. Hãy đăng nhập TikTok trên trình duyệt, đóng trình duyệt rồi chạy lại.")
        raise SystemExit(1)
    if not verify_session():
        log("❌ Cookie TikTok không còn hợp lệ. Hãy xuất lại tiktok_cookies.json rồi chạy lại.")
        raise SystemExit(1)
    log("🧪 Echo="+os.getenv("TIKTOK_ECHO_TEST","0"))
    log("🤖 AutoReply="+os.getenv("TIKTOK_AUTO_REPLY","0"))
    log("👉 Gửi DM từ account TikTok khác để test. Ctrl+C để dừng.\n")
    try:
        if IS_FROZEN:
            raise SystemExit(asyncio.run(_lttk_module("main")._run_all()))
        raise SystemExit(subprocess.call([sys.executable,"main.py"],cwd=str(LTTK)))
    except KeyboardInterrupt:
        log("\n👋 Stop")

if __name__=="__main__":
    main()
