from flask import Flask, request, jsonify, session, redirect, url_for, g
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, datetime
from datetime import timedelta

app = Flask(__name__)

# [FIX] Ye line Railway ke SSL/HTTPS ko handle karegi
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.environ.get("SECRET_KEY", "nihit_final_fix_v2")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

DATABASE = 'nihit_v2.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, chats INT, imgs INT, PRIMARY KEY(user, date))")
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
def ai(msg, cid, img=None):
    try:
        db = get_db()
        hist = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6", (cid,)).fetchall()
        msgs = [{"role": "assistant" if r in ["assistant", "ai"] else "user", "content": c} for r, c in hist[::-1]]
        
        user_content = [{"type": "text", "text": msg}]
        if img:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": "You are Perplex AI made by Nihit Kumar."}] + msgs + [{"role": "user", "content": user_content}]
        }
        
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", 
                         headers={"Authorization": f"Bearer {os.environ.get('OPENROUTER_KEY')}"}, 
                         json=payload, timeout=60)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e: return f"Error: {str(e)}"

# --- Routes ---
@app.route("/")
def index(): return redirect("/chat") if "user" in session else UI_LOGIN

@app.route("/login")
def login():
    # [FIX] Force HTTPS here
    return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route("/callback")
def callback():
    # Railway environment fix
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 
    token = google.authorize_access_token()
    resp = google.get('https://www.googleapis.com/oauth2/v2/userinfo')
    session["user"] = resp.json()["email"]
    return redirect("/chat")

@app.route("/chat")
def chat_page():
    if "user" not in session: return redirect("/")
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    u = get_db().execute("SELECT chats FROM usage WHERE user=? AND date=?", (session['user'], today)).fetchone()
    return UI_HTML.replace("{{c}}", str(u[0] if u else 0))

@app.route("/send", methods=["POST"])
def send_msg():
    db = get_db()
    user, data = session.get("user"), request.form
    msg, img, cid = data.get("msg"), data.get("image"), data.get("chat")
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    
    u = db.execute("SELECT chats, imgs FROM usage WHERE user=? AND date=?", (user, today)).fetchone()
    c_count, i_count = (u[0], u[1]) if u else (0, 0)
    if c_count >= 50: return jsonify({"reply": "Limit over!"})

    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))
    
    reply = ai(msg, cid, img)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.execute("INSERT OR REPLACE INTO usage VALUES(?,?,?,?)", (user, today, c_count + 1, i_count + (1 if img else 0)))
    db.commit()
    return jsonify({"reply": reply, "chat_id": cid, "c": c_count+1})

@app.route("/history")
def history():
    rows = get_db().execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session['user'],)).fetchall()
    return jsonify(rows)

@app.route("/clear", methods=["POST"])
def clear():
    get_db().execute("DELETE FROM chats WHERE user=?", (session['user'],))
    get_db().commit()
    return jsonify({"success": True})

# UI simplified for fast loading
UI_LOGIN = """<body style="background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
<div style="text-align:center;"><h1>Perplex AI</h1><a href="/login" style="background:#fff;color:#000;padding:12px 24px;text-decoration:none;border-radius:30px;font-weight:bold;">Login with Google</a></div></body>"""

UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Nihit AI</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { margin:0; background:#0d0d0d; color:#eee; font-family:sans-serif; display:flex; height:100vh; }
        .sidebar { width:260px; background:#161616; border-right:1px solid #222; padding:15px; display:flex; flex-direction:column; }
        .main { flex:1; display:flex; flex-direction:column; }
        #box { flex:1; overflow-y:auto; padding:30px 10%; display:flex; flex-direction:column; gap:20px; }
        .bubble { padding:12px; border-radius:15px; max-width:80%; }
        .user { align-self:flex-end; background:#2563eb; }
        .ai { align-self:flex-start; border:1px solid #333; }
        .input-bar { padding:20px 10%; border-top:1px solid #222; }
        .bar { background:#1e1e1e; border-radius:30px; padding:10px 20px; display:flex; gap:10px; }
        input { flex:1; background:transparent; border:none; color:white; outline:none; }
        button { background:white; border:none; padding:8px 15px; border-radius:20px; cursor:pointer; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h3>Nihit AI</h3>
        <button onclick="location.href='/chat'">+ New Chat</button>
        <div id="hist" style="flex:1; margin-top:20px;"></div>
        <div style="font-size:12px; color:#555;">Usage: <span id="c-tag">{{c}}</span>/50</div>
    </div>
    <div class="main">
        <div id="box"></div>
        <div class="input-bar">
            <div id="p-box" style="display:none;"><img id="p-img" style="height:50px; margin-bottom:5px;"></div>
            <div class="bar">
                <span onclick="document.getElementById('f').click()" style="cursor:pointer;">🖼️</span>
                <input type="file" id="f" hidden onchange="pre(this)">
                <input type="text" id="in" placeholder="Ask Nihit..." onkeypress="if(event.key=='Enter')send()">
                <button onclick="send()">Send</button>
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
            const d = await r.json();
            cid = d.chat_id;
            b.innerHTML += `<div class="bubble ai">${d.reply}</div>`;
            document.getElementById("c-tag").innerText = d.c;
            img = null; document.getElementById("p-box").style.display="none";
            b.scrollTop = b.scrollHeight; loadHist();
        }
        function pre(i) {
            const r = new FileReader();
            r.onload = (e) => { img = e.target.result.split(',')[1]; document.getElementById("p-img").src = e.target.result; document.getElementById("p-box").style.display = "block"; };
            r.readAsDataURL(i.files[0]);
        }
        function loadHist() { fetch("/history").then(r=>r.json()).then(data => { document.getElementById("hist").innerHTML = data.map(c => `<div style="padding:10px; cursor:pointer;" onclick="location.href='/chat?c=${c[0]}'"># ${c[1]}</div>`).join(''); }); }
        loadHist();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
