import os, sqlite3, time, requests, json, base64
from flask import Flask, request, jsonify, session, redirect, url_for, g
from authlib.integrations.flask_client import OAuth
from datetime import datetime
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get("SECRET_KEY", "perplex_final_stable_v10")

# ================= DATABASE MANAGEMENT =================
DATABASE = 'perplex_ai.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS user_memory(user TEXT PRIMARY KEY, memory TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, count INTEGER, PRIMARY KEY(user, date))")
        db.commit()
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# ================= AUTH SETUP =================
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)

# ================= AI ENGINE =================
def get_ai_response(msg, chat_id, user_email, img_b64=None):
    try:
        db = get_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mem = db.execute("SELECT memory FROM user_memory WHERE user=?", (user_email,)).fetchone()
        
        hist = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 8", (chat_id,)).fetchall()
        messages = [{"role": h[0], "content": h[1]} for h in reversed(hist)]

        sys_prompt = f"Sense: {now}. Memory: {mem[0] if mem else ''}. Always use ```html blocks for code to trigger Canvas."
        
        user_content = [{"type": "text", "text": msg}]
        if img_b64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": sys_prompt}] + messages + [{"role": "user", "content": user_content}]
        }
        
        r = requests.post("[https://openrouter.ai/api/v1/chat/completions](https://openrouter.ai/api/v1/chat/completions)", 
                         headers={"Authorization": f"Bearer {os.environ.get('OPENROUTER_KEY')}"}, 
                         json=payload, timeout=45)
        return r.json()['choices'][0]['message']['content']
    except Exception as e: return f"Error: {str(e)}"

# ================= ROUTES =================
@app.route("/")
def index(): return redirect("/chat") if "user" in session else '<a href="/login">Login with Google</a>'

@app.route("/login")
def login(): return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route("/callback")
def callback():
    session["user"] = google.authorize_access_token().get('userinfo', google.get("[https://www.googleapis.com/oauth2/v2/userinfo](https://www.googleapis.com/oauth2/v2/userinfo)").json())["email"]
    return redirect("/chat")

@app.route("/chat")
def chat():
    if "user" not in session: return redirect("/")
    today = datetime.now().strftime('%Y-%m-%d')
    res = get_db().execute("SELECT count FROM usage WHERE user=? AND date=?", (session['user'], today)).fetchone()
    return UI_HTML.replace("{{count}}", str(res[0] if res else 0))

@app.route("/send", methods=["POST"])
def send_msg():
    db = get_db()
    user = session.get("user")
    msg, img, cid = request.form.get("msg"), request.form.get("image"), request.form.get("chat")
    
    today = datetime.now().strftime('%Y-%m-%d')
    res = db.execute("SELECT count FROM usage WHERE user=? AND date=?", (user, today)).fetchone()
    current_count = res[0] if res else 0
    
    if current_count >= 50: return jsonify({"reply": "Limit Exceeded (50/50)"})
    
    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:25]))
    
    reply = get_ai_response(msg, cid, user, img)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.execute("INSERT OR REPLACE INTO usage VALUES(?,?,?)", (user, today, current_count + 1))
    db.commit()
    return jsonify({"reply": reply, "chat_id": cid, "new_count": current_count + 1})

@app.route("/history")
def history():
    rows = get_db().execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session['user'],)).fetchall()
    return jsonify(rows)

@app.route("/clear", methods=["POST"])
def clear():
    get_db().execute("DELETE FROM chats WHERE user=?", (session['user'],))
    get_db().commit()
    return jsonify({"status": "ok"})

# ================= UI HTML =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { margin:0; background:#0d0d0d; color:#eee; font-family: sans-serif; display:flex; height:100vh; overflow:hidden; }
        .sidebar { width:260px; background:#161616; border-right:1px solid #222; display:flex; flex-direction:column; padding:15px; }
        .main { flex:1; display:flex; position:relative; overflow:hidden; }
        #chat-pane { flex:1; display:flex; flex-direction:column; transition: 0.3s; }
        #box { flex:1; overflow-y:auto; padding:20px 10%; display:flex; flex-direction:column; gap:15px; }
        .msg { padding:12px; border-radius:12px; max-width:85%; font-size:15px; }
        .user { align-self:flex-end; background:#2563eb; }
        .assistant { align-self:flex-start; background:#222; border:1px solid #333; }
        .input-area { padding:20px 10%; border-top:1px solid #222; }
        .bar { background:#1e1e1e; border-radius:25px; padding:10px 20px; display:flex; align-items:center; gap:12px; border:1px solid #333; }
        input[type="text"] { flex:1; background:transparent; border:none; color:white; outline:none; }
        #canvas { width:50%; background:#000; border-left:1px solid #222; display:none; flex-direction:column; }
        .plus-btn { cursor:pointer; font-size:24px; color:#888; position:relative; }
        .plus-menu { position:absolute; bottom:55px; left:0; background:#222; border:1px solid #444; border-radius:8px; display:none; flex-direction:column; width:160px; z-index:100; }
        .plus-menu div { padding:12px; font-size:14px; cursor:pointer; }
        #send-btn { background:#2563eb; color:white; border:none; padding:8px 15px; border-radius:20px; cursor:pointer; }
        #stop-btn { background:#d32f2f; color:white; border:none; padding:8px 15px; border-radius:20px; cursor:pointer; display:none; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2 style="color:#2563eb; margin:0 0 15px 0;">PERPLEX</h2>
        <button onclick="location.reload()" style="background:#333; color:white; padding:10px; border:none; border-radius:8px; cursor:pointer;">+ New Chat</button>
        <input type="text" id="srch" placeholder="Search chats..." oninput="filter()" style="margin-top:10px; padding:8px; background:#000; border:1px solid #333; color:white; border-radius:5px;">
        <div id="hist" style="flex:1; overflow-y:auto; margin-top:15px;"></div>
        <div onclick="toggleSett()" style="cursor:pointer; color:#555; font-size:13px; padding-top:10px;">⚙️ Settings</div>
    </div>

    <div class="main">
        <div id="chat-pane">
            <div style="position:absolute; top:10px; left:20px; font-size:12px; color:#444;">Daily Usage: <span id="u-tag">{{count}}</span>/50</div>
            <div id="box"></div>
            <div class="input-area">
                <div id="pre-box" style="display:none; margin-bottom:10px;"><img id="pre-img" style="height:50px; border-radius:5px;"></div>
                <div class="bar">
                    <div class="plus-btn" onclick="togglePlus()">+
                        <div class="plus-menu" id="p-menu">
                            <div onclick="document.getElementById('f').click()">🖼️ Upload Photo</div>
                            <div onclick="openCanvas()">🎨 Canvas</div>
                        </div>
                    </div>
                    <input type="file" id="f" hidden onchange="pre(this)">
                    <input type="text" id="in" placeholder="Ask Nihit's AI..." onkeypress="if(event.key=='Enter')send()">
                    <button id="send-btn" onclick="send()">Send</button>
                    <button id="stop-btn" onclick="stop()">Stop</button>
                </div>
            </div>
        </div>

        <div id="canvas">
            <div style="padding:10px; background:#111; display:flex; justify-content:space-between;">
                <span>Canvas</span>
                <div><button onclick="run()">Run</button> <button onclick="openCanvas(false)">✕</button></div>
            </div>
            <textarea id="code" style="flex:1; background:#000; color:#0f0; padding:15px; border:none; font-family:monospace; outline:none; resize:none;"></textarea>
            <iframe id="out" style="height:45%; background:white; border:none;"></iframe>
        </div>
    </div>

    <div id="sett" style="display:none; position:fixed; bottom:60px; left:20px; background:#222; padding:15px; border-radius:10px; border:1px solid #444; z-index:1000;">
        <div onclick="clearAll()" style="color:red; cursor:pointer;">🗑️ Clear All Chat</div>
        <div onclick="alert(document.cookie)" style="margin-top:10px; cursor:pointer;">🍪 Cookies Pref</div>
    </div>

    <script>
        let cid = null, img = null, controller = null;

        async function send() {
            const i = document.getElementById("in");
            if(!i.value && !img) return;
            const b = document.getElementById("box");
            b.innerHTML += `<div class="msg user">${i.value}</div>`;
            const val = i.value; i.value = "";
            b.scrollTop = b.scrollHeight;

            document.getElementById("send-btn").style.display = "none";
            document.getElementById("stop-btn").style.display = "block";

            controller = new AbortController();
            const fd = new FormData();
            fd.append("msg", val); fd.append("chat", cid);
            if(img) fd.append("image", img);

            try {
                const r = await fetch("/send", {method:"POST", body:fd, signal: controller.signal});
                const d = await r.json();
                cid = d.chat_id;
                let reply = d.reply;
                if(reply.includes("```html")) {
                    openCanvas(true);
                    document.getElementById("code").value = reply.match(/```html([\\s\\S]*?)```/)[1].trim();
                    reply = reply.replace(/```html[\\s\\S]*?```/g, "*(Code sent to Canvas)*");
                }
                b.innerHTML += `<div class="msg assistant">${reply}</div>`;
                document.getElementById("u-tag").innerText = d.new_count || "{{count}}";
            } catch(e) {}

            document.getElementById("send-btn").style.display = "block";
            document.getElementById("stop-btn").style.display = "none";
            img = null; document.getElementById("pre-box").style.display="none";
            b.scrollTop = b.scrollHeight;
            loadHist();
        }

        function stop() { if(controller) controller.abort(); }
        function pre(i) {
            const r = new FileReader();
            r.onload = (e) => {
                img = e.target.result.split(',')[1];
                document.getElementById("pre-img").src = e.target.result;
                document.getElementById("pre-box").style.display = "block";
            };
            r.readAsDataURL(i.files[0]); togglePlus();
        }
        function openCanvas(s=true) { document.getElementById("canvas").style.display = s?"flex":"none"; document.getElementById("chat-pane").style.flex = s?"0.5":"1"; }
        function run() { const f = document.getElementById("out").contentWindow.document; f.open(); f.write(document.getElementById("code").value); f.close(); }
        function togglePlus() { const m = document.getElementById("p-menu"); m.style.display = m.style.display==="flex"?"none":"flex"; }
        function toggleSett() { const s = document.getElementById("sett"); s.style.display = s.style.display==="block"?"none":"block"; }
        function filter() { const q = document.getElementById("srch").value.toLowerCase(); document.querySelectorAll(".h-i").forEach(i => i.style.display = i.innerText.toLowerCase().includes(q)?"block":"none"); }
        function loadHist() { fetch("/history").then(r=>r.json()).then(data => { const h = document.getElementById("hist"); h.innerHTML = ""; data.forEach(c => h.innerHTML += `<div class="h-i" style="padding:10px; cursor:pointer; border-bottom:1px solid #222;">${c[1]}</div>`); }); }
        function clearAll() { if(confirm("Clear history?")) fetch("/clear", {method:"POST"}).then(()=>location.reload()); }
        loadHist();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
```[cite: 1]
