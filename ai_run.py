from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os
from datetime import timedelta

# Deployment environment fixes
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.getenv("SECRET_KEY", "nihit_x_fire_ultra_pro_max_v3")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# ================= DATABASE (Permanent Storage) =================
def init_db():
    conn = sqlite3.connect("perplex_ai.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    # Memory table: Sabse important
    conn.execute("CREATE TABLE IF NOT EXISTS user_memory(user TEXT PRIMARY KEY, memory_data TEXT)")
    conn.commit()
    return conn

db = init_db()

# ================= GOOGLE LOGIN =================
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)

# ================= AI ENGINE (Strict Memory + Pro Coding) =================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, user_email):
    try:
        # 1. Database se permanent memory nikalna
        mem_res = db.execute("SELECT memory_data FROM user_memory WHERE user=?", (user_email,)).fetchone()
        permanent_memory = mem_res[0] if mem_res else "No info saved yet."

        # 2. Current Chat ki history
        history_rows = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 10", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history_rows)]

        # 3. System Prompt: AI ko 'Strict' banana
        system_prompt = f"""
        Identity: You are Perplex AI by Nihit kr.
        STRICT MEMORY: You MUST remember this about the user: {permanent_memory}.
        If the user asks 'What is my name?' or about themselves, answer using this memory.

        CODING RULE: If HTML/CSS/JS is asked, output ONLY the code. No explanations. 
        Start directly with <!DOCTYPE html>.
        
        Tone: Friendly Hinglish (Bhai, Bro).
        """

        headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
        
        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": system_prompt}] + chat_history + [{"role": "user", "content": msg}],
            "temperature": 0.3 # Accurate and consistent
        }

        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
        reply = r.json()["choices"][0]["message"]["content"]

        # 4. Smart Memory Update: Agar user ne kuch bataya toh save karo
        trigger_words = ["my name is", "mera naam", "i am", "yaad rakho", "remember"]
        if any(word in msg.lower() for word in trigger_words):
            # Purani memory mein naya info add karna
            new_mem = f"{permanent_memory} | User said: {msg}" if permanent_memory != "No info saved yet." else msg
            db.execute("INSERT OR REPLACE INTO user_memory VALUES(?,?)", (user_email, new_mem[-1000:]))
            db.commit()

        return reply
    except Exception as e: return f"Bhai error hai: {str(e)}"

# ================= ROUTES =================

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return '''<body style="background:#000; color:white; display:flex; justify-content:center; align-items:center; height:100vh; font-family:sans-serif;">
              <div style="text-align:center;">
                <h1 style="font-size:50px;">PERPLEX AI</h1>
                <p style="color:#555;">Smart Memory & Pro Coding Enabled</p><br>
                <a href="/login" style="padding:15px 35px; background:white; color:black; text-decoration:none; border-radius:50px; font-weight:bold;">Login with Google</a>
              </div></body>'''

@app.route("/login")
def login():
    # Strict HTTPS for Google Login
    r_uri = url_for('callback', _external=True, _scheme='https')
    return google.authorize_redirect(r_uri)

@app.route("/callback")
def callback():
    google.authorize_access_token()
    info = google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
    session["user"] = info["email"]
    return redirect("/chat")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/chat")
def chat_ui():
    if "user" not in session: return redirect("/")
    return UI_HTML

@app.route("/send", methods=["POST"])
def send_msg():
    user = session.get("user")
    cid, msg = request.form.get("chat"), request.form.get("msg")
    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))
    
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    reply = get_ai_response(msg, cid, user)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.commit()
    return jsonify({"reply": reply, "chat_id": cid})

@app.route("/chats")
def get_chats():
    user = session.get("user")
    rows = db.execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (user,)).fetchall()
    return jsonify(rows)

@app.route("/msgs")
def get_msgs():
    cid = request.args.get("c")
    rows = db.execute("SELECT role, content FROM messages WHERE chat_id=?", (cid,)).fetchall()
    return jsonify(rows)

# ================= UI DESIGN =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI Pro</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { margin:0; background:#0e0e0e; color:#eee; font-family:sans-serif; display:flex; height:100vh; }
        .sidebar { width:260px; background:#151515; border-right:1px solid #222; display:flex; flex-direction:column; padding:15px; }
        .main { flex:1; display:flex; flex-direction:column; background:#0e0e0e; }
        #box { flex:1; overflow-y:auto; padding:30px 15%; display:flex; flex-direction:column; gap:20px; }
        .msg { padding:12px 18px; border-radius:15px; max-width:85%; line-height:1.6; font-size:15px; }
        .user { align-self:flex-end; background:#2563eb; color:white; border-radius:20px 20px 0 20px; }
        .assistant { align-self:flex-start; background:#1e1e1e; border:1px solid #333; }
        pre { background:#000; padding:15px; border-radius:10px; overflow-x:auto; color:#4ade80; border:1px solid #222; }
        .input-wrap { padding:20px 15%; background:#0e0e0e; }
        .in-box { background:#1e1e1e; border-radius:30px; padding:10px 20px; display:flex; border:1px solid #333; }
        input { flex:1; background:transparent; border:none; color:white; outline:none; font-size:16px; }
        .chat-link { padding:12px; cursor:pointer; color:#888; border-radius:8px; margin-bottom:5px; font-size:14px; }
        .chat-link:hover { background:#222; color:white; }
    </style>
</head>
<body>
    <div class="sidebar">
        <b style="color:#2563eb; font-size:20px; margin-bottom:20px;">PERPLEX AI</b>
        <div onclick="location.href='/chat'" style="cursor:pointer; background:#2563eb; padding:12px; text-align:center; border-radius:10px; margin-bottom:20px; font-weight:bold;">+ New Chat</div>
        <div id="list" style="flex:1; overflow-y:auto;"></div>
        <a href="/logout" style="color:#ef4444; text-decoration:none; font-size:13px; margin-top:10px;">Sign Out</a>
    </div>
    <div class="main">
        <div id="box"></div>
        <div class="input-wrap">
            <div class="in-box">
                <input type="text" id="msg" placeholder="Ask anything..." onkeypress="if(event.key=='Enter')send()">
                <button onclick="send()" style="background:none; border:none; color:#2563eb; font-size:20px; cursor:pointer;">➤</button>
            </div>
        </div>
    </div>
    <script>
        let currentCid = null;
        function send() {
            const m = document.getElementById("msg"); if(!m.value) return;
            const b = document.getElementById("box");
            b.innerHTML += `<div class="msg user">${m.value}</div>`;
            const fd = new FormData(); fd.append("chat", currentCid); fd.append("msg", m.value);
            m.value = ""; b.scrollTop = b.scrollHeight;
            fetch("/send", {method:"POST", body:fd}).then(r=>r.json()).then(d => {
                currentCid = d.chat_id;
                let reply = d.reply;
                if(reply.includes("<!DOCTYPE")) reply = `<pre>${reply.replace(/</g, "&lt;")}</pre>`;
                else reply = reply.replace(/\\n/g, "<br>");
                b.innerHTML += `<div class="msg assistant">${reply}</div>`;
                b.scrollTop = b.scrollHeight;
                load();
            });
        }
        function load() {
            fetch("/chats").then(r=>r.json()).then(data => {
                const l = document.getElementById("list"); l.innerHTML = "";
                data.forEach(c => {
                    let d = document.createElement("div"); d.className = "chat-link";
                    d.innerText = c[1]; d.onclick = () => openChat(c[0]);
                    l.appendChild(d);
                });
            });
        }
        function openChat(id) {
            currentCid = id;
            fetch("/msgs?c="+id).then(r=>r.json()).then(msgs => {
                const b = document.getElementById("box"); b.innerHTML = "";
                msgs.forEach(m => {
                    let content = m[1];
                    if(content.includes("<!DOCTYPE")) content = `<pre>${content.replace(/</g, "&lt;")}</pre>`;
                    b.innerHTML += `<div class="msg ${m[0]}">${content}</div>`;
                });
                b.scrollTop = b.scrollHeight;
            });
        }
        load();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
