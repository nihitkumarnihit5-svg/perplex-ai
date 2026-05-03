from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os
from datetime import timedelta

# Railway/Render par HTTPS errors hatane ke liye
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.getenv("SECRET_KEY", "nihit_x_fire_ultra_pro_max_88")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# ================= DATABASE (Memory Storage) =================
def init_db():
    conn = sqlite3.connect("perplex_ai.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS user_memory(user TEXT PRIMARY KEY, memory_data TEXT)")
    conn.commit()
    return conn

db = init_db()

# ================= GOOGLE LOGIN CONFIG =================
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)

# ================= AI ENGINE (Pro Coding + Memory) =================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, user_email):
    try:
        # Step 1: Memory Load (Nihit ka naam ya details)
        mem_res = db.execute("SELECT memory_data FROM user_memory WHERE user=?", (user_email,)).fetchone()
        saved_memory = mem_res[0] if mem_res else "Unknown"

        # Step 2: History Load
        history_rows = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 10", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history_rows)]

        # Step 3: Pro System Prompt
        system_prompt = f"""
        - Identity: You are 'Perplex AI' by Nihit kr. 
        - User Info: Your user's saved data is: {saved_memory}. 
        - Tone: Friendly Hinglish.
        - CRITICAL RULE (Coding): If the user asks for HTML/Code, provide ONLY the raw code block. No 'Here is your code' or 'Hope this helps'. Just START with <!DOCTYPE html>.
        - CRITICAL RULE (Memory): If user mentions their name or info, ALWAYS remember it for future chats.
        """

        headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
        
        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": system_prompt}] + chat_history + [{"role": "user", "content": msg}],
            "temperature": 0.5 # Low temperature for accurate coding
        }

        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
        reply = r.json()["choices"][0]["message"]["content"]

        # Step 4: Smart Save (Auto-Detection)
        if any(x in msg.lower() for x in ["my name is", "mera naam", "yaad rakho", "remember"]):
            db.execute("INSERT OR REPLACE INTO user_memory VALUES(?,?)", (user_email, msg))
            db.commit()

        return reply
    except Exception as e: return f"Error: {str(e)}"

# ================= ROUTES =================

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return '''<body style="background:#000; color:white; display:flex; justify-content:center; align-items:center; height:100vh; font-family:sans-serif;">
              <div style="text-align:center;">
                <h1 style="letter-spacing:5px;">PERPLEX AI</h1>
                <a href="/login" style="padding:12px 30px; background:white; color:black; text-decoration:none; border-radius:5px; font-weight:bold;">Login with Google</a>
              </div></body>'''

@app.route("/login")
def login():
    redirect_uri = url_for('callback', _external=True, _scheme='https')
    return google.authorize_redirect(redirect_uri)

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

# ================= PRO UI =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI | Pro</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { margin:0; background:#0b0b0b; color:#eee; font-family:sans-serif; display:flex; height:100vh; }
        .side { width:250px; background:#111; border-right:1px solid #222; display:flex; flex-direction:column; padding:15px; }
        .main { flex:1; display:flex; flex-direction:column; }
        #box { flex:1; overflow-y:auto; padding:20px; display:flex; flex-direction:column; gap:15px; }
        .msg { padding:12px 18px; border-radius:12px; max-width:80%; word-wrap:break-word; line-height:1.5; }
        .user { align-self:flex-end; background:#2563eb; color:white; }
        .assistant { align-self:flex-start; background:#1e1e1e; border:1px solid #333; }
        pre { background:#000; padding:10px; border-radius:8px; overflow-x:auto; color:#0f0; }
        .input-bar { padding:20px; background:#0b0b0b; display:flex; gap:10px; }
        input { flex:1; background:#1a1a1a; border:1px solid #333; color:white; padding:12px; border-radius:8px; outline:none; }
        button { background:#2563eb; color:white; border:none; padding:0 20px; border-radius:8px; cursor:pointer; }
        .chat-link { padding:10px; cursor:pointer; border-bottom:1px solid #222; font-size:13px; color:#999; }
        .chat-link:hover { color:white; background:#1a1a1a; }
    </style>
</head>
<body>
    <div class="side">
        <b style="color:#2563eb; margin-bottom:20px;">PERPLEX AI</b>
        <div onclick="location.reload()" style="cursor:pointer; background:#222; padding:10px; text-align:center; border-radius:5px; margin-bottom:10px;">+ New Chat</div>
        <div id="list" style="flex:1; overflow-y:auto;"></div>
        <a href="/logout" style="color:#666; text-decoration:none; font-size:12px;">Sign Out</a>
    </div>
    <div class="main">
        <div id="box"></div>
        <div class="input-bar">
            <input type="text" id="msg" placeholder="Ask Nihit's AI..." onkeypress="if(event.key=='Enter')send()">
            <button onclick="send()">Send</button>
        </div>
    </div>
    <script>
        let currentCid = null;
        function send() {
            const m = document.getElementById("msg"); if(!m.value) return;
            const b = document.getElementById("box");
            b.innerHTML += `<div class="msg user">${m.value}</div>`;
            const fd = new FormData(); fd.append("chat", currentCid); fd.append("msg", m.value);
            m.value = "";
            fetch("/send", {method:"POST", body:fd}).then(r=>r.json()).then(d => {
                currentCid = d.chat_id;
                let reply = d.reply.replace(/```html|```/g, ""); // Clean code view
                if(reply.includes("<!DOCTYPE")) reply = `<pre>${reply.replace(/</g, "&lt;")}</pre>`;
                b.innerHTML += `<div class="msg assistant">${reply}</div>`;
                b.scrollTop = b.scrollHeight;
                loadChats();
            });
        }
        function loadChats() {
            fetch("/chats").then(r=>r.json()).then(data => {
                const l = document.getElementById("list"); l.innerHTML = "";
                data.forEach(c => {
                    let div = document.createElement("div"); div.className = "chat-link";
                    div.innerText = c[1]; div.onclick = () => openChat(c[0]);
                    l.appendChild(div);
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
        loadChats();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
