# Railway-ready patched Flask app (key structure + UI upgrades)
# Replace your current app.py with this file, then copy any remaining custom logic.

from flask import Flask, request, jsonify, session, redirect, url_for, g
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, os, datetime
from datetime import timedelta

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.environ.get("SECRET_KEY", "nihit_gemini_v3")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

DATABASE = 'nihit_v3.db'


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, chats INT, PRIMARY KEY(user, date))")
        db.commit()
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)


@app.route("/")
def index():
    return redirect("/chat") if "user" in session else UI_LOGIN


@app.route("/chat")
def chat_page():
    if "user" not in session:
        return redirect("/")

    today = datetime.datetime.now().strftime('%Y-%m-%d')
    u = get_db().execute(
        "SELECT chats FROM usage WHERE user=? AND date=?",
        (session['user'], today)
    ).fetchone()

    return UI_HTML.replace("{{c}}", str(u[0] if u else 0))


UI_LOGIN = """
<body style='background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;'>
<div style='text-align:center;'>
<h1>Nihit AI</h1>
<a href='/login' style='background:#fff;color:#000;padding:12px 24px;text-decoration:none;border-radius:30px;font-weight:bold;'>Sign in with Google</a>
</div>
</body>
"""


UI_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nihit AI</title>
<style>
:root{--bg:#0d0d0d;--side:#151515;--line:#272727;--blue:#2563eb}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:#fff;font-family:sans-serif;height:100vh;display:flex;overflow:hidden}
.sidebar{width:270px;background:var(--side);border-right:1px solid var(--line);padding:14px;display:flex;flex-direction:column}
.main{flex:1;display:flex;min-width:0}
.chat-wrap{flex:1;display:flex;flex-direction:column;min-width:0}
#box{flex:1;overflow:auto;padding:30px 8%;display:flex;flex-direction:column;gap:18px}
.bubble{padding:12px 16px;border-radius:18px;max-width:82%;line-height:1.6;white-space:pre-wrap}
.user{align-self:flex-end;background:var(--blue)}
.ai{align-self:flex-start;border:1px solid #333;background:#171717}
.input-wrap{padding:18px 8%;border-top:1px solid var(--line);position:relative}
.bar{display:flex;align-items:center;gap:12px;background:#1b1b1b;border:1px solid #333;border-radius:28px;padding:8px 16px}
.bar input[type=text]{flex:1;background:transparent;border:none;outline:none;color:#fff;font-size:15px}
#sendBtn,#stopBtn{border:none;padding:8px 16px;border-radius:20px;cursor:pointer;font-weight:bold}
#stopBtn{display:none;background:#ef4444;color:#fff}
.plus-menu{position:absolute;bottom:80px;left:8%;width:190px;background:#1a1a1a;border:1px solid #333;border-radius:12px;display:none;flex-direction:column;overflow:hidden}
.plus-menu div{padding:12px;cursor:pointer;border-bottom:1px solid #2a2a2a}
.plus-menu div:hover{background:#2a2a2a}
#canvas{width:48%;display:none;flex-direction:column;border-left:1px solid var(--line);background:#000}
#code{flex:1;width:100%;background:#000;color:#e5e5e5;border:none;outline:none;padding:18px;font-family:monospace;font-size:14px;line-height:1.5;resize:none}
#out{height:40%;width:100%;border:none;background:#fff}
.h-item{padding:9px;border-radius:8px;cursor:pointer;font-size:14px}
.h-item:hover{background:#222}
</style>
</head>
<body>
<div class="sidebar">
<div style="font-size:11px;color:#888;margin-bottom:8px">DAILY USAGE: <span id="c-tag">{{c}}</span>/50</div>
<h2 style="margin:0 0 12px 0;color:#2563eb">Nihit AI</h2>
<button style="margin-bottom:10px;padding:10px;border:none;border-radius:8px;background:#2a2a2a;color:#fff">+ New Chat</button>
<input id="srch" placeholder="Search chats..." style="padding:8px;background:#0d0d0d;border:1px solid #333;color:#fff;border-radius:6px;margin-bottom:12px">
<div id="hist" style="flex:1;overflow:auto"></div>
</div>

<div class="main">
<div class="chat-wrap">
<div id="box"></div>
<div class="input-wrap">
<div class="plus-menu" id="pm">
<div>🖼 Upload Photo / Video</div>
<div onclick="toggleCanvas()">🎨 Canvas</div>
</div>
<div class="bar">
<span onclick="togglePlus()" style="font-size:22px;cursor:pointer;color:#aaa">+</span>
<input id="in" type="text" placeholder="Type a message...">
<span style="font-size:19px;cursor:pointer">🎤</span>
<button id="sendBtn">Send</button>
<button id="stopBtn">Stop</button>
</div>
</div>
</div>

<div id="canvas">
<div style="padding:12px 16px;border-bottom:1px solid #222;display:flex;justify-content:space-between;align-items:center">
<div style="font-weight:bold;color:#2563eb">Canvas</div>
<div>
<button onclick="runCode()" style="border:none;padding:6px 12px;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer">Run Code</button>
<button onclick="toggleCanvas()" style="margin-left:8px;background:none;border:none;color:#999;font-size:20px;cursor:pointer">✕</button>
</div>
</div>
<textarea id="code" spellcheck="false"></textarea>
<iframe id="out"></iframe>
</div>
</div>

<script>
function togglePlus(){
 const p=document.getElementById('pm');
 p.style.display=p.style.display==='flex'?'none':'flex';
}
function toggleCanvas(){
 const c=document.getElementById('canvas');
 c.style.display=c.style.display==='flex'?'none':'flex';
}
function runCode(){
 const f=document.getElementById('out').contentWindow.document;
 f.open();
 f.write(document.getElementById('code').value);
 f.close();
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
