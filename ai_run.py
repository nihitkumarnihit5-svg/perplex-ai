from flask import Flask, request, jsonify, session, redirect, url_for, g
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, datetime
from datetime import timedelta

app = Flask(__name__)
# Railway production proxy support
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.environ.get("SECRET_KEY", "nihit_final_v13")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

DATABASE = 'perplex_ai.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, count INTEGER, PRIMARY KEY(user, date))")
        db.commit()
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None: db.close()

# --- Google Auth ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)

# --- AI Core ---
def get_ai_response(msg, chat_id, img_base64=None):
    try:
        db = get_db()
        history = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 4", (chat_id,)).fetchall()
        msgs = [{"role": h[0], "content": h[1]} for h in reversed(history)]
        
        user_content = [{"type": "text", "text": msg}]
        if img_base64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": "You are Perplex AI. Keep it simple."}] + msgs + [{"role": "user", "content": user_content}]
        }

        r = requests.post("https://openrouter.ai/api/v1/chat/completions", 
                         headers={"Authorization": f"Bearer {os.environ.get('OPENROUTER_KEY')}"}, 
                         json=payload, timeout=40)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return "Bhai server down hai ya API key check karo."

# --- Routes ---
@app.route("/")
def index():
    return redirect("/chat") if "user" in session else UI_LOGIN

@app.route("/login")
def login():
    return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route("/callback")
def callback():
    try:
        token = google.authorize_access_token()
        # FIXED URL: Removed brackets
        resp = google.get('https://www.googleapis.com/oauth2/v2/userinfo')
        user_info = resp.json()
        session["user"] = user_info["email"]
        return redirect("/chat")
    except Exception as e:
        return f"Login Error: {str(e)}"

@app.route("/chat")
def chat_page():
    if "user" not in session: return redirect("/")
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    res = get_db().execute("SELECT count FROM usage WHERE user=? AND date=?", (session['user'], today)).fetchone()
    return UI_HTML.replace("{{usage}}", str(res[0] if res else 0))

@app.route("/send", methods=["POST"])
def send_msg():
    db = get_db()
    user = session.get("user")
    data = request.form
    msg, img, cid = data.get("msg"), data.get("image"), data.get("chat")
    
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    res = db.execute("SELECT count FROM usage WHERE user=? AND date=?", (user, today)).fetchone()
    u_count = res[0] if res else 0
    if u_count >= 50: return jsonify({"reply": "Daily limit over!"})

    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))
    
    reply = get_ai_response(msg, cid, img)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.execute("INSERT OR REPLACE INTO usage VALUES(?,?,?)", (user, today, u_count + 1))
    db.commit()
    
    return jsonify({"reply": reply, "chat_id": cid, "new_usage": u_count + 1})

@app.route("/history")
def history():
    rows = get_db().execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session.get('user'),)).fetchall()
    return jsonify(rows)

# --- Clean UI ---
UI_LOGIN = """<body style="background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
<div style="text-align:center;"><h1>Perplex AI</h1><a href="/login" style="background:#fff;color:#000;padding:12px 24px;text-decoration:none;border-radius:30px;font-weight:bold;">Login with Google</a></div></body>"""

UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { margin:0; background:#0d0d0d; color:#eee; font-family:sans-serif; display:flex; height:100vh; }
        .sidebar { width:260px; background:#161616; border-right:1px solid #222; display:flex; flex-direction:column; padding:15px; }
        .main { flex:1; display:flex; flex-direction:column; }
        #box { flex:1; overflow-y:auto; padding:30px 15%; display:flex; flex-direction:column; gap:20px; }
        .bubble { padding:12px; border-radius:12px; max-width:85%; line-height:1.5; }
        .user { align-self:flex-end; background:#2563eb; }
        .ai { align-self:flex-start; background:#1e1e1e; border:1px solid #333; }
        .input-bar { padding:20px 15%; border-top:1px solid #222; }
        .bar { background:#1e1e1e; border-radius:30px; padding:10px 20px; display:flex; align-items:center; gap:10px; }
        input[type="text"] { flex:1; background:transparent; border:none; color:white; outline:none; }
        #sendBtn { background:#fff; border:none; padding:8px 15px; border-radius:20px; cursor:pointer; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2 style="color:#2563eb">Perplex AI</h2>
        <button onclick="location.reload()" style="background:#333; color:white; padding:10px; border:none; border-radius:8px;">+ New Chat</button>
        <div id="hist" style="flex:1; overflow-y:auto; margin-top:20px;"></div>
        <div style="font-size:12px; color:#555;">Usage: <span id="u-tag">{{usage}}</span>/50</div>
    </div>
    <div class="main">
        <div id="box"></div>
        <div class="input-bar">
            <div id="p-box" style="display:none;"><img id="p-img" style="height:50px; border-radius:5px; margin-bottom:5px;"></div>
            <div class="bar">
                <span style="cursor:pointer; color:#888;" onclick="document.getElementById('f').click()">+</span>
                <input type="file" id="f" hidden onchange="pre(this)">
                <input type="text" id="in" placeholder="Ask anything..." onkeypress="if(event.key=='Enter')send()">
                <button id="sendBtn" onclick="send()">Send</button>
            </div>
        </div>
    </div>
    <script>
        let cid = null, img = null;
        async function send() {
            const i = document.getElementById("in"); if(!i.value && !img) return;
            const b = document.getElementById("box");
            b.innerHTML += `<div class="bubble user">${i.value}</div>`;
            const val = i.value; i.value = ""; b.scrollTop = b.scrollHeight;
            const fd = new FormData(); fd.append("msg", val); fd.append("chat", cid); if(img) fd.append("image", img);
            const r = await fetch("/send", {method:"POST", body:fd});
            const d = await r.json(); cid = d.chat_id;
            b.innerHTML += `<div class="bubble ai">${d.reply}</div>`;
            document.getElementById("u-tag").innerText = d.new_usage;
            img = null; document.getElementById("p-box").style.display="none";
            b.scrollTop = b.scrollHeight; loadHist();
        }
        function pre(i) {
            const r = new FileReader();
            r.onload = (e) => { img = e.target.result.split(',')[1]; document.getElementById("p-img").src = e.target.result; document.getElementById("p-box").style.display = "block"; };
            r.readAsDataURL(i.files[0]);
        }
        function loadHist() { fetch("/history").then(r=>r.json()).then(data => { const h = document.getElementById("hist"); h.innerHTML = data.map(c => `<div style="padding:8px; font-size:14px; cursor:pointer;" onclick="location.href='/chat?c=${c[0]}'"># ${c[1]}</div>`).join(''); }); }
        loadHist();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
