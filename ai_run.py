from flask import Flask, request, jsonify, session, redirect, url_for, g
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, datetime
from datetime import timedelta

app = Flask(__name__)
# Railway production proxy fix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.environ.get("SECRET_KEY", "nihit_ultra_fix_v14")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Database ka naam change kiya taaki structure reset ho jaye
DATABASE = 'nihit_v14.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        # Sahi table structure
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
def get_ai_response(msg, chat_id, img_base64=None):
    try:
        db = get_db()
        history = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6", (chat_id,)).fetchall()
        msgs = [{"role": h[0], "content": h[1]} for h in reversed(history)]
        
        user_content = [{"type": "text", "text": msg}]
        if img_base64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}})

        # AI Identify karega ki Nihit Kr. ne banaya hai
        sys_p = "You are an AI assistant. If asked who made you, say: 'I was developed by Nihit Kr.' Use ```html for any code."
        
        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": sys_p}] + msgs + [{"role": "user", "content": user_content}]
        }
        r = requests.post("[https://openrouter.ai/api/v1/chat/completions](https://openrouter.ai/api/v1/chat/completions)", 
                         headers={"Authorization": f"Bearer {os.environ.get('OPENROUTER_KEY')}"}, 
                         json=payload, timeout=60)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e: return f"AI Error: {str(e)}"

# --- Routes ---
@app.route("/")
def index(): return redirect("/chat") if "user" in session else UI_LOGIN

@app.route("/login")
def login():
    # Railway ke liye https force karna zaroori hai
    return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route("/callback")
def callback():
    try:
        token = google.authorize_access_token()
        resp = google.get('[https://www.googleapis.com/oauth2/v2/userinfo](https://www.googleapis.com/oauth2/v2/userinfo)')
        session["user"] = resp.json()["email"]
        return redirect("/chat")
    except Exception as e:
        return f"Auth Error: {str(e)}. Check your Google Console Redirect URI."

@app.route("/chat")
def chat_page():
    if "user" not in session: return redirect("/")
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    u = get_db().execute("SELECT chats, imgs FROM usage WHERE user=? AND date=?", (session['user'], today)).fetchone()
    return UI_HTML.replace("{{c}}", str(u[0] if u else 0))

@app.route("/send", methods=["POST"])
def send_msg():
    db = get_db()
    user, data = session.get("user"), request.form
    msg, img, cid = data.get("msg"), data.get("image"), data.get("chat")
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    
    u = db.execute("SELECT chats, imgs FROM usage WHERE user=? AND date=?", (user, today)).fetchone()
    c_count, i_count = (u[0], u[1]) if u else (0, 0)

    if c_count >= 50: return jsonify({"reply": "Daily limit (50) reached!"})
    if img and i_count >= 5: return jsonify({"reply": "Limit Exceeded: 5 images only per day."})

    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))
    
    reply = get_ai_response(msg, cid, img)
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

# --- UI HTML (Gemini Style) ---
UI_LOGIN = """<body style="background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
<div style="text-align:center;"><h1>NihitXFire AI</h1><a href="/login" style="background:#fff;color:#000;padding:12px 24px;text-decoration:none;border-radius:30px;font-weight:bold;">Sign in with Google</a></div></body>"""

UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Nihit AI Pro</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root { --bg: #0d0d0d; --side: #161616; --blue: #2563eb; }
        body { margin:0; background:var(--bg); color:#eee; font-family: sans-serif; display:flex; height:100vh; overflow:hidden; }
        .sidebar { width:260px; background:var(--side); border-right:1px solid #222; display:flex; flex-direction:column; padding:15px; transition: 0.3s; }
        .main { flex:1; display:flex; position:relative; }
        .chat-area { flex:1; display:flex; flex-direction:column; }
        #box { flex:1; overflow-y:auto; padding:30px 12%; display:flex; flex-direction:column; gap:20px; }
        .bubble { padding:12px 18px; border-radius:18px; max-width:85%; line-height:1.6; font-size:15px; }
        .user { align-self:flex-end; background:var(--blue); color:white; }
        .ai { align-self:flex-start; background:transparent; border:1px solid #333; }
        .input-wrap { padding:20px 12%; border-top:1px solid #222; position:relative; }
        .bar { background:#1e1e1e; border-radius:30px; padding:10px 20px; display:flex; align-items:center; gap:12px; border:1px solid #333; }
        input[type="text"] { flex:1; background:transparent; border:none; color:white; outline:none; font-size:16px; }
        #canvas { flex:1; background:#000; display:none; flex-direction:column; border-left:1px solid #222; }
        .p-menu { position:absolute; bottom:85px; left:12%; background:#222; border:1px solid #444; border-radius:10px; display:none; flex-direction:column; width:180px; z-index:100; }
        .p-menu div { padding:12px; cursor:pointer; font-size:14px; }
        .p-menu div:hover { background:#333; }
        #sendBtn { background:#fff; border:none; padding:8px 16px; border-radius:20px; font-weight:bold; cursor:pointer; }
        #stopBtn { background:#ef4444; color:white; border:none; padding:8px 16px; border-radius:20px; font-weight:bold; cursor:pointer; display:none; }
    </style>
</head>
<body>
    <div class="sidebar" id="sidebar">
        <h2 style="color:var(--blue); margin-bottom:20px;">Nihit AI</h2>
        <button onclick="location.href='/chat'" style="background:#333; color:white; padding:12px; border:none; border-radius:10px; cursor:pointer; margin-bottom:15px;">+ New Chat</button>
        <input type="text" id="srch" placeholder="Search chats..." oninput="filter()" style="padding:10px; background:#000; border:1px solid #333; color:white; border-radius:8px; margin-bottom:15px;">
        <div id="hist" style="flex:1; overflow-y:auto;"></div>
        <div style="font-size:12px; color:#666; margin-bottom:10px;">Daily Chats: <span id="c-tag">{{c}}</span>/50</div>
        <div onclick="toggleSett()" style="cursor:pointer; color:#888; font-size:14px;">⚙️ Settings</div>
    </div>

    <div class="main">
        <div class="chat-area" id="chatArea">
            <div id="box"></div>
            <div class="input-wrap">
                <div id="p-box" style="display:none; margin-bottom:10px;"><img id="p-img" style="height:60px; border-radius:8px; border:1px solid #444;"></div>
                <div class="p-menu" id="pm">
                    <div onclick="document.getElementById('f').click()">🖼️ Upload Photo</div>
                    <div onclick="toggleCvs()">🎨 Open Canvas</div>
                </div>
                <div class="bar">
                    <span style="cursor:pointer; font-size:24px; color:#888;" onclick="togglePlus()">+</span>
                    <input type="file" id="f" hidden onchange="pre(this)">
                    <input type="text" id="in" placeholder="Ask Nihit's AI..." onkeypress="if(event.key=='Enter')send()">
                    <span onclick="startMic()" style="cursor:pointer; font-size:20px;">🎤</span>
                    <button id="sendBtn" onclick="send()">Send</button>
                    <button id="stopBtn" onclick="stop()">Stop</button>
                </div>
            </div>
        </div>
        <div id="canvas">
            <div style="padding:12px; background:#111; display:flex; justify-content:space-between; border-bottom:1px solid #222;">
                <span>Canvas Mode</span>
                <div><button onclick="run()">Run Code</button> <button onclick="toggleCvs()">✕</button></div>
            </div>
            <textarea id="code" style="flex:1; background:#000; color:#0f0; padding:15px; border:none; font-family:monospace; outline:none; resize:none;"></textarea>
            <iframe id="out" style="height:45%; background:white; width:100%; border:none;"></iframe>
        </div>
    </div>

    <div id="sett" style="display:none; position:fixed; bottom:60px; left:20px; background:#222; padding:15px; border-radius:10px; border:1px solid #444; width:220px; z-index:200;">
        <div onclick="clearAll()" style="color:#ef4444; cursor:pointer; font-weight:bold; padding:5px 0;">🗑️ Clear All Chats</div>
        <div onclick="alert(document.cookie)" style="color:#888; cursor:pointer; margin-top:10px; font-size:12px;">🍪 Cookie Preferences</div>
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

            const fd = new FormData();
            fd.append("msg", val); fd.append("chat", cid); if(img) fd.append("image", img);

            try {
                const r = await fetch("/send", {method:"POST", body:fd, signal: ctrl.signal});
                const d = await r.json();
                if(d.reply.includes("reached")) { alert(d.reply); return; }
                cid = d.chat_id;
                let reply = d.reply;
                if(reply.includes("```html")) {
                    document.getElementById("canvas").style.display = "flex";
                    document.getElementById("code").value = reply.match(/```html([\\s\\S]*?)```/)[1].trim();
                    reply = reply.replace(/```html[\\s\\S]*?```/g, "*(Code displayed in Canvas)*");
                }
                b.innerHTML += `<div class="bubble ai">${reply}</div>`;
                document.getElementById("c-tag").innerText = d.c || "0";
            } catch(e) { if(e.name !== 'AbortError') b.innerHTML += `<div class="bubble ai">Error: Request Failed</div>`; }

            document.getElementById("sendBtn").style.display = "block";
            document.getElementById("stopBtn").style.display = "none";
            img = null; document.getElementById("p-box").style.display="none";
            b.scrollTop = b.scrollHeight; loadHist();
        }

        function stop() { if(ctrl) ctrl.abort(); }
        function pre(i) {
            const r = new FileReader();
            r.onload = (e) => {
                img = e.target.result.split(',')[1];
                document.getElementById("p-img").src = e.target.result;
                document.getElementById("p-box").style.display = "block";
                document.getElementById("pm").style.display = "none";
            };
            r.readAsDataURL(i.files[0]);
        }
        function togglePlus() { const m = document.getElementById("pm"); m.style.display = m.style.display==="flex"?"none":"flex"; }
        function toggleCvs() { const c = document.getElementById("canvas"); c.style.display = c.style.display==="flex"?"none":"flex"; }
        function run() { const f = document.getElementById("out").contentWindow.document; f.open(); f.write(document.getElementById("code").value); f.close(); }
        function toggleSett() { const s = document.getElementById("sett"); s.style.display = s.style.display==="block"?"none":"block"; }
        function filter() { const q = document.getElementById("srch").value.toLowerCase(); document.querySelectorAll(".h-i").forEach(i => i.style.display = i.innerText.toLowerCase().includes(q)?"block":"none"); }
        function loadHist() { fetch("/history").then(r=>r.json()).then(data => { const h = document.getElementById("hist"); h.innerHTML = data.map(c => `<div class="h-i" style="padding:10px; cursor:pointer; font-size:14px; border-radius:8px;" onclick="location.href='/chat?c=${c[0]}'"># ${c[1]}</div>`).join(''); }); }
        function clearAll() { if(confirm("Sab delete kar dein?")) fetch("/clear", {method:"POST"}).then(()=>location.reload()); }
        function startMic() { const rec = new (window.SpeechRecognition || window.webkitSpeechRecognition)(); rec.onresult = (e) => { document.getElementById("in").value = e.results[0][0].transcript; }; rec.start(); }
        loadHist();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
