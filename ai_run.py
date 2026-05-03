from flask import Flask, request, jsonify, session, redirect, url_for, g
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, datetime
from datetime import timedelta

app = Flask(__name__)
# Railway HTTPS support fix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.environ.get("SECRET_KEY", "nihit_final_v4_fix")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Database version badal diya taaki 500 error khatam ho jaye
DATABASE = 'nihit_v4.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        # Sahi table structure reset ke liye
        db.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, chats INT, PRIMARY KEY(user, date))")
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
        msgs = []
        for r, c in hist[::-1]:
            role = "assistant" if r in ["assistant", "ai"] else "user"
            msgs.append({"role": role, "content": c})

        user_content = [{"type": "text", "text": msg}]
        if img:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [
                {"role": "system", "content": "You are Perplex AI developed by Nihit Kr. If asked about your creator, say Nihit Kr. Use ```html for code."}
            ] + msgs + [{"role": "user", "content": user_content}]
        }
        
        r = requests.post("[https://openrouter.ai/api/v1/chat/completions](https://openrouter.ai/api/v1/chat/completions)", 
                         headers={"Authorization": f"Bearer {os.environ.get('OPENROUTER_KEY')}"}, 
                         json=payload, timeout=60)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e: return f"Error: {str(e)}"

# --- Routes ---
@app.route("/")
def index(): return redirect("/chat") if "user" in session else UI_LOGIN

@app.route("/login")
def login():
    return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route("/callback")
def callback():
    try:
        token = google.authorize_access_token()
        resp = google.get('[https://www.googleapis.com/oauth2/v2/userinfo](https://www.googleapis.com/oauth2/v2/userinfo)')
        session["user"] = resp.json()["email"]
        return redirect("/chat")
    except Exception: return redirect("/")

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
    
    u = db.execute("SELECT chats FROM usage WHERE user=? AND date=?", (user, today)).fetchone()
    c_count = u[0] if u else 0
    if c_count >= 50: return jsonify({"reply": "Limit reached!"})

    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))
    
    reply = ai(msg, cid, img)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.execute("INSERT OR REPLACE INTO usage VALUES(?,?,?)", (user, today, c_count + 1))
    db.commit()
    return jsonify({"reply": reply, "chat_id": cid, "c": c_count+1})

@app.route("/history")
def history():
    rows = get_db().execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session['user'],)).fetchall()
    return jsonify(rows)

# --- UI (Gemini Look) ---
UI_LOGIN = """<body style="background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
<div style="text-align:center;"><h1>Nihit AI</h1><a href="/login" style="background:#fff;color:#000;padding:12px 24px;text-decoration:none;border-radius:30px;font-weight:bold;">Sign in with Google</a></div></body>"""

UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Nihit AI Pro</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root { --bg: #0d0d0d; --side: #161616; --blue: #2563eb; }
        body { margin:0; background:var(--bg); color:#eee; font-family: sans-serif; display:flex; height:100vh; overflow:hidden; }
        .sidebar { width:260px; background:var(--side); border-right:1px solid #222; display:flex; flex-direction:column; padding:15px; }
        .main { flex:1; display:flex; position:relative; }
        .chat-container { flex:1; display:flex; flex-direction:column; min-width:400px; }
        #box { flex:1; overflow-y:auto; padding:40px 10%; display:flex; flex-direction:column; gap:25px; }
        .bubble { padding:12px 18px; border-radius:18px; max-width:85%; line-height:1.6; }
        .user { align-self:flex-end; background:var(--blue); }
        .ai { align-self:flex-start; border:1px solid #333; }
        .input-wrap { padding:20px 10%; border-top:1px solid #222; position:relative; }
        .bar { background:#1e1e1e; border-radius:30px; padding:10px 20px; display:flex; align-items:center; gap:12px; border:1px solid #333; }
        input[type="text"] { flex:1; background:transparent; border:none; color:white; outline:none; font-size:16px; }
        #canvas { flex:1.2; background:#000; display:none; flex-direction:column; border-left:1px solid #222; }
        .p-menu { position:absolute; bottom:85px; left:10%; background:#222; border-radius:10px; display:none; flex-direction:column; width:180px; z-index:100; border:1px solid #444; }
        .p-menu div { padding:12px; cursor:pointer; border-bottom:1px solid #333; font-size:14px; }
        #sendBtn { background:#fff; border:none; padding:8px 16px; border-radius:20px; font-weight:bold; cursor:pointer; }
        #stopBtn { background:#ef4444; color:white; border:none; padding:8px 16px; border-radius:20px; font-weight:bold; cursor:pointer; display:none; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div style="font-size:11px; color:#555;">DAILY LIMIT: <span id="c-tag">{{c}}</span>/50</div>
        <h2 style="color:var(--blue); margin:10px 0;">Nihit AI</h2>
        <button onclick="location.href='/chat'" style="padding:10px; border-radius:8px; border:none; cursor:pointer; background:#333; color:white; margin-bottom:15px;">+ New Chat</button>
        <input type="text" id="srch" placeholder="Search..." oninput="filter()" style="padding:8px; background:#000; border:1px solid #333; color:white; border-radius:5px; margin-bottom:15px;">
        <div id="hist" style="flex:1; overflow-y:auto;"></div>
    </div>
    <div class="main">
        <div class="chat-container">
            <div id="box"></div>
            <div class="input-wrap">
                <div id="p-box" style="display:none; margin-bottom:10px;"><img id="p-img" style="height:60px; border-radius:5px;"></div>
                <div class="p-menu" id="pm">
                    <div onclick="document.getElementById('f').click()">🖼️ Upload Photo/Video</div>
                    <div onclick="toggleCvs()">🎨 Open Canvas</div>
                </div>
                <div class="bar">
                    <span onclick="togglePlus()" style="cursor:pointer; font-size:24px; color:#888;">+</span>
                    <input type="file" id="f" hidden onchange="pre(this)">
                    <input type="text" id="in" placeholder="Ask Nihit..." onkeypress="if(event.key=='Enter')send()">
                    <span onclick="startMic()" style="cursor:pointer; font-size:20px;">🎤</span>
                    <button id="sendBtn" onclick="send()">Send</button>
                    <button id="stopBtn" onclick="stop()">Stop</button>
                </div>
            </div>
        </div>
        <div id="canvas">
            <div style="padding:15px; background:#111; display:flex; justify-content:space-between; border-bottom:1px solid #222;">
                <span>Canvas</span>
                <div><button onclick="run()">Run Code</button> <button onclick="toggleCvs()">✕</button></div>
            </div>
            <textarea id="code" style="flex:1; background:#000; color:#0f0; padding:20px; font-family:monospace; border:none; outline:none; font-size:14px; resize:none;"></textarea>
            <iframe id="out" style="height:40%; background:white; width:100%; border:none;"></iframe>
        </div>
    </div>
    <script>
        let cid = null, img = null, ctrl = null;
        async function send() {
            const i = document.getElementById("in"); if(!i.value && !img) return;
            const b = document.getElementById("box");
            b.innerHTML += `<div class="bubble user">${i.value}</div>`;
            const val = i.value; i.value = ""; b.scrollTop = b.scrollHeight;
            document.getElementById("sendBtn").style.display = "none";
            document.getElementById("stopBtn").style.display = "block";
            ctrl = new AbortController();
            const fd = new FormData(); fd.append("msg", val); fd.append("chat", cid); if(img) fd.append("image", img);
            try {
                const r = await fetch("/send", {method:"POST", body:fd, signal: ctrl.signal});
                const d = await r.json();
                cid = d.chat_id;
                let reply = d.reply;
                if(reply.includes("```html")) {
                    document.getElementById("canvas").style.display = "flex";
                    document.getElementById("code").value = reply.match(/```html([\\s\\S]*?)
```/)[1].trim();
                }
                b.innerHTML += `<div class="bubble ai">${reply}</div>`;
                document.getElementById("c-tag").innerText = d.c;
            } catch(e) {}
            document.getElementById("sendBtn").style.display = "block";
            document.getElementById("stopBtn").style.display = "none";
            img = null; document.getElementById("p-box").style.display="none";
            b.scrollTop = b.scrollHeight; loadHist();
        }
        function stop() { if(ctrl) ctrl.abort(); }
        function pre(i) {
            const r = new FileReader();
            r.onload = (e) => { img = e.target.result.split(',')[1]; document.getElementById("p-img").src = e.target.result; document.getElementById("p-box").style.display = "block"; document.getElementById("pm").style.display = "none"; };
            r.readAsDataURL(i.files[0]);
        }
        function togglePlus() { const m = document.getElementById("pm"); m.style.display = m.style.display==="flex"?"none":"flex"; }
        function toggleCvs() { const c = document.getElementById("canvas"); c.style.display = c.style.display==="flex"?"none":"flex"; }
        function run() { const f = document.getElementById("out").contentWindow.document; f.open(); f.write(document.getElementById("code").value); f.close(); }
        function filter() { const q = document.getElementById("srch").value.toLowerCase(); document.querySelectorAll(".h-item").forEach(i => i.style.display = i.innerText.toLowerCase().includes(q)?"block":"none"); }
        function startMic() { const rec = new (window.SpeechRecognition || window.webkitSpeechRecognition)(); rec.onresult = (e) => { document.getElementById("in").value = e.results[0][0].transcript; }; rec.start(); }
        function loadHist() { fetch("/history").then(r=>r.json()).then(data => { document.getElementById("hist").innerHTML = data.map(c => `<div class="h-item" style="padding:10px; cursor:pointer;" onclick="location.href='/chat?c=${c[0]}'"># ${c[1]}</div>`).join(''); }); }
        loadHist();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
