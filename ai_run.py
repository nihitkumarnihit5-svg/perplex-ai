from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, base64, re
from datetime import datetime, timedelta

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get("SECRET_KEY", "perplex_ultra_pro_v7")

# ================= DATABASE (Sab kuch save rahega) =================
def init_db():
    conn = sqlite3.connect("perplex_ai.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS user_memory(user TEXT PRIMARY KEY, memory_data TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, msg_count INTEGER, img_count INTEGER, PRIMARY KEY(user, date))")
    conn.commit()
    return conn

db = init_db()

# ================= GOOGLE AUTH =================
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)

# ================= LIMIT CHECKER =================
def get_usage(user):
    today = datetime.now().strftime('%Y-%m-%d')
    res = db.execute("SELECT msg_count, img_count FROM usage WHERE user=? AND date=?", (user, today)).fetchone()
    if not res:
        db.execute("INSERT INTO usage VALUES(?,?,0,0)", (user, today))
        db.commit()
        return 0, 0
    return res

# ================= AI LOGIC (Vision + Memory) =================
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, user_email, img_base64=None):
    try:
        mem_res = db.execute("SELECT memory_data FROM user_memory WHERE user=?", (user_email,)).fetchone()
        memory = mem_res[0] if mem_res else "Nihit is the boss."

        history_rows = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history_rows)]

        system_prompt = f"Identity: Perplex AI by Nihit kr. Memory: {memory}. RULE: If HTML/CSS code is asked, wrap it in ```html ... ```. Separate text and code."
        
        user_content = [{"type": "text", "text": msg}]
        if img_base64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": system_prompt}] + chat_history + [{"role": "user", "content": user_content}]
        }
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {OPENROUTER_KEY}"}, json=payload, timeout=40)
        return r.json()["choices"][0]["message"]["content"]
    except: return "Bhai error aa gaya. Check API."

# ================= ROUTES =================

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return '<body style="background:#000;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;"><div><h1>PERPLEX AI</h1><a href="/login" style="color:#000;background:#fff;padding:12px 25px;text-decoration:none;border-radius:30px;font-weight:bold;">Login</a></div></body>'

@app.route("/login")
def login(): return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route("/callback")
def callback():
    token = google.authorize_access_token()
    info = google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
    session["user"] = info["email"]
    return redirect("/chat")

@app.route("/chat")
def chat_page():
    if "user" not in session: return redirect("/")
    msg_c, img_c = get_usage(session['user'])
    return UI_HTML.replace("{{msg_count}}", str(msg_c))

@app.route("/send", methods=["POST"])
def send():
    user = session.get("user")
    msg, img, cid = request.form.get("msg"), request.form.get("image"), request.form.get("chat")
    msg_c, img_c = get_usage(user)

    if img and img_c >= 5: return jsonify({"reply": "Exceeded Limit! Ek din mein sirf 5 images."})
    if msg_c >= 50: return jsonify({"reply": "Exceeded Limit! Aaj ke 50 messages pure ho gaye."})

    if not cid or cid in ["null", "undefined"]:
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:25]))

    reply = get_ai_response(msg, cid, user, img)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    
    today = datetime.now().strftime('%Y-%m-%d')
    col = "img_count" if img else "msg_count"
    db.execute(f"UPDATE usage SET {col} = {col} + 1 WHERE user=? AND date=?", (user, today))
    db.commit()
    
    new_msg_c, _ = get_usage(user)
    return jsonify({"reply": reply, "chat_id": cid, "new_count": new_msg_c})

@app.route("/chats")
def get_chats():
    rows = db.execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session['user'],)).fetchall()
    return jsonify(rows)

@app.route("/delete_all", methods=["POST"])
def delete_all():
    db.execute("DELETE FROM chats WHERE user=?", (session['user'],))
    db.commit(); return jsonify({"status":"ok"})

# ================= UI =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI Pro</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root { --bg: #0a0a0a; --panel: #141414; --blue: #2563eb; --border: #222; }
        body { margin:0; background:var(--bg); color:#eee; font-family:sans-serif; display:flex; height:100vh; overflow:hidden; }
        .sidebar { width:260px; background:var(--panel); border-right:1px solid var(--border); display:flex; flex-direction:column; padding:15px; }
        .main { flex:1; display:flex; position:relative; }
        .chat-area { flex:1; display:flex; flex-direction:column; border-right:1px solid var(--border); }
        .canvas { width:50%; display:none; flex-direction:column; background:#000; transition: 0.3s; }
        #box { flex:1; overflow-y:auto; padding:20px 10%; display:flex; flex-direction:column; gap:15px; }
        .msg { padding:12px; border-radius:15px; max-width:85%; line-height:1.5; font-size:15px; }
        .user { align-self:flex-end; background:var(--blue); }
        .assistant { align-self:flex-start; background:var(--panel); border:1px solid var(--border); }
        .input-wrap { padding:20px 10%; }
        .input-box { background:var(--panel); border:1px solid var(--border); border-radius:15px; padding:10px; display:flex; align-items:center; gap:10px; position:relative; }
        input[type="text"] { flex:1; background:transparent; border:none; color:white; outline:none; font-size:16px; }
        .plus-btn { font-size:24px; cursor:pointer; color:#888; padding:0 5px; }
        .plus-menu { position:absolute; bottom:60px; left:10px; background:var(--panel); border:1px solid var(--border); border-radius:10px; display:none; flex-direction:column; min-width:140px; z-index:100; }
        .plus-menu div { padding:12px; font-size:14px; cursor:pointer; border-bottom:1px solid #222; }
        .plus-menu div:hover { background:#222; }
        .usage-badge { position:fixed; top:10px; left:275px; background:var(--panel); padding:5px 12px; border-radius:20px; font-size:12px; border:1px solid var(--border); }
        .settings-btn { position:absolute; top:15px; right:15px; cursor:pointer; opacity:0.6; }
        .canvas-header { padding:10px; background:#111; display:flex; justify-content:space-between; align-items:center; }
        #codeEditor { flex:1; background:#000; color:#4ade80; padding:15px; border:none; font-family:monospace; resize:none; outline:none; }
    </style>
</head>
<body>
    <div class="usage-badge">Usage: <span id="u-count">{{msg_count}}</span>/50</div>
    <div class="sidebar">
        <h3 style="color:var(--blue);">PERPLEX AI</h3>
        <button onclick="location.reload()" style="padding:10px; border-radius:8px; border:none; background:#222; color:white; cursor:pointer;">+ New Chat</button>
        <input type="text" id="search" placeholder="Search chats..." oninput="searchChats()" style="margin:10px 0; background:transparent; border:1px solid var(--border); padding:8px; color:white; border-radius:5px;">
        <div id="list" style="flex:1; overflow-y:auto;"></div>
        <div onclick="toggleSettings()" style="cursor:pointer; color:#555; font-size:13px;">⚙️ Settings</div>
    </div>

    <div class="main">
        <div class="chat-area">
            <div id="box"></div>
            <div class="input-wrap">
                <div class="input-box">
                    <div class="plus-btn" onclick="togglePlus()">+</div>
                    <div class="plus-menu" id="p-menu">
                        <div onclick="document.getElementById('f-in').click()">🖼️ Upload Photo</div>
                        <div onclick="toggleCanvas()">🎨 Open Canvas</div>
                    </div>
                    <input type="file" id="f-in" hidden onchange="handleFile(this)">
                    <input type="text" id="u-input" placeholder="Ask Nihit's AI..." onkeypress="if(event.key=='Enter')send()">
                    <button id="s-btn" onclick="send()" style="background:var(--blue); color:white; border:none; padding:8px 18px; border-radius:10px; cursor:pointer;">Send</button>
                </div>
            </div>
        </div>

        <div class="canvas" id="canvasArea">
            <div class="canvas-header">
                <span>Code Canvas</span>
                <div>
                    <button onclick="runCode()" style="background:#22c55e; border:none; color:white; padding:5px 12px; border-radius:5px; cursor:pointer; margin-right:10px;">Run</button>
                    <span onclick="toggleCanvas()" style="color:#ff4b4b; cursor:pointer; font-weight:bold;">✕</span>
                </div>
            </div>
            <textarea id="codeEditor" spellcheck="false"></textarea>
            <iframe id="preview" style="height:40%; background:white; border:none;"></iframe>
        </div>
    </div>

    <div id="settings" style="position:fixed; top:60px; right:20px; background:var(--panel); border:1px solid var(--border); padding:15px; border-radius:10px; display:none; z-index:1000;">
        <div onclick="clearHistory()" style="color:red; cursor:pointer; margin-bottom:10px;">🗑️ Clear All Chat</div>
        <div onclick="alert(document.cookie)" style="cursor:pointer;">🍪 View Cookies</div>
        <div onclick="toggleSettings()" style="color:#888; cursor:pointer; text-align:center; font-size:12px;">Close</div>
    </div>

    <script>
        let currentCid = null;
        let abortCtrl = null;

        async function send() {
            const input = document.getElementById("u-input");
            const btn = document.getElementById("s-btn");
            const val = input.value.trim();
            if(!val) return;

            if(btn.innerText === "Stop") {
                abortCtrl.abort();
                btn.innerText = "Send";
                return;
            }

            const box = document.getElementById("box");
            box.innerHTML += `<div class="msg user">${val}</div>`;
            input.value = "";
            btn.innerText = "Stop";
            box.scrollTop = box.scrollHeight;

            abortCtrl = new AbortController();
            const fd = new FormData();
            fd.append("msg", val);
            fd.append("chat", currentCid);

            try {
                const r = await fetch("/send", {method:"POST", body:fd, signal: abortCtrl.signal});
                const d = await r.json();
                currentCid = d.chat_id;
                document.getElementById("u-count").innerText = d.new_count || 0;

                let reply = d.reply;
                const codeMatch = reply.match(/```(?:html|css|js)?\s*([\s\S]*?)```/);
                if(codeMatch) {
                    document.getElementById("canvasArea").style.display = "flex";
                    document.getElementById("codeEditor").value = codeMatch[1].trim();
                    reply = reply.replace(/```[\s\S]*?```/g, "*(Code sent to Canvas)*");
                }
                box.innerHTML += `<div class="msg assistant">${reply.replace(/\\n/g, "<br>")}</div>`;
                btn.innerText = "Send";
                box.scrollTop = box.scrollHeight;
                load();
            } catch(e) { btn.innerText = "Send"; }
        }

        function handleFile(el) {
            const reader = new FileReader();
            reader.onload = () => {
                const fd = new FormData();
                fd.append("msg", "Analyze this image");
                fd.append("image", reader.result.split(',')[1]);
                fd.append("chat", currentCid);
                fetch("/send", {method:"POST", body:fd}).then(r=>r.json()).then(d => {
                    document.getElementById("box").innerHTML += `<div class="msg assistant">${d.reply}</div>`;
                });
            };
            reader.readAsDataURL(el.files[0]);
        }

        function togglePlus() {
            const m = document.getElementById("p-menu");
            m.style.display = m.style.display === "flex" ? "none" : "flex";
        }

        function toggleCanvas() {
            const c = document.getElementById("canvasArea");
            c.style.display = c.style.display === "flex" ? "none" : "flex";
        }

        function toggleSettings() {
            const s = document.getElementById("settings");
            s.style.display = s.style.display === "block" ? "none" : "block";
        }

        function runCode() {
            const code = document.getElementById("codeEditor").value;
            const frame = document.getElementById("preview").contentWindow.document;
            frame.open(); frame.write(code); frame.close();
        }

        function clearHistory() { if(confirm("Delete all chats?")) fetch("/delete_all", {method:"POST"}).then(()=>location.reload()); }

        function searchChats() {
            const q = document.getElementById("search").value.toLowerCase();
            document.querySelectorAll(".c-link").forEach(i => {
                i.style.display = i.innerText.toLowerCase().includes(q) ? "block" : "none";
            });
        }

        function load() {
            fetch("/chats").then(r=>r.json()).then(data => {
                const l = document.getElementById("list"); l.innerHTML = "";
                data.forEach(c => {
                    l.innerHTML += `<div class="c-link" onclick="openChat('${c[0]}')" style="padding:10px; cursor:pointer; font-size:14px; border-bottom:1px solid #222;">${c[1]}</div>`;
                });
            });
        }
        load();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
