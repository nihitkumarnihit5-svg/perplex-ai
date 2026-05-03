from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, base64, re
from datetime import timedelta, datetime

app = Flask(__name__)
# Railway fixed redirections
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.environ.get("SECRET_KEY", "perplex_ultra_pro_v9_ultimate")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# ================= DATABASE SETUP (Memory, History, Usage) =================
def init_db():
    conn = sqlite3.connect("perplex_ai.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS user_memory(user TEXT PRIMARY KEY, memory_data TEXT)")
    # Usage table to track message and image counts
    conn.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, msg_count INTEGER, img_count INTEGER, PRIMARY KEY(user, date))")
    conn.commit()
    return conn

db = init_db()

# ================= GOOGLE AUTH CONFIG =================
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)

# ================= LIMITS & USAGE LOGIC =================
def get_daily_usage(user):
    today = datetime.now().strftime('%Y-%m-%d')
    res = db.execute("SELECT msg_count, img_count FROM usage WHERE user=? AND date=?", (user, today)).fetchone()
    if not res:
        db.execute("INSERT INTO usage VALUES(?,?,0,0)", (user, today))
        db.commit()
        return 0, 0
    return res

# ================= AI ENGINE (Pro, Memory, Sense, Vision) =================
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, user_email, img_base64=None):
    try:
        # Load Sense & Memory context
        mem_res = db.execute("SELECT memory_data FROM user_memory WHERE user=?", (user_email,)).fetchone()
        user_memory_context = mem_res[0] if mem_res else "No previous personal context saved."
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Load Chat History
        history_rows = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history_rows)]

        # Updated System Prompt (Senior Developer, Gemini Style, Sense, Memory)
        system_prompt = f"""You are 'Perplex AI' by Nihit kr. You talk in friendly Hinglish. 
        [SENSE]: Current time is {current_time}. You know today's context.
        [MEMORY]: Facts about user: {user_memory_context}. Use this naturally.
        [CAPABILITY]: If user asks for HTML/CSS/JS, act as Senior Full-Stack Dev.
        CRITICAL RULE (Canvas): If giving large code, wrap it strictly in ```html ... ``` or other language backticks. Separate text explanation from code blocks.
        If user reveals new fact, update memory mentally."""
        
        user_content = [{"type": "text", "text": msg}]
        if img_base64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": system_prompt}] + chat_history + [{"role": "user", "content": user_content}],
            "temperature": 0.6
        }

        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {OPENROUTER_KEY}"}, json=payload, timeout=60)
        ai_reply = r.json()["choices"][0]["message"]["content"]

        # Simple auto-memory save logic (e.g., if user says "my name is Nihit")
        memory_keywords = ["my name is", "i live in", "i love", "mera naam"]
        if any(keyword in msg.lower() for keyword in memory_keywords):
            db.execute("INSERT OR REPLACE INTO user_memory VALUES(?,?)", (user_email, f"{user_memory_context} | {msg}"[-1000:])) # Keep last 1000 chars
            db.commit()

        return ai_reply
    except: return "Bhai error aa gaya server mein."

# ================= ROUTES =================

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return UI_HTML_LOGIN

@app.route("/login")
def login():
    return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route("/callback")
def callback():
    token = google.authorize_access_token()
    info = google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
    session["user"] = info["email"]
    return redirect("/chat")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/chat")
def chat_page():
    if "user" not in session: return redirect("/")
    msg_count, img_count = get_daily_usage(session['user'])
    # Replace initial usage count in HTML
    return UI_HTML.replace("{{msg_usage}}", str(msg_count)).replace("{{img_usage}}", str(img_count))

@app.route("/send", methods=["POST"])
def send_msg():
    user = session.get("user")
    if not user: return jsonify({"reply": "Unauthorized"}), 401
    
    msg, img, cid = request.form.get("msg"), request.form.get("image"), request.form.get("chat")
    msg_count, img_count = get_daily_usage(user)

    # Limit Checks
    if img and img_count >= 5: return jsonify({"reply": "❌ Image Limit Exceeded (5 per day)!"})
    if msg_count >= 50: return jsonify({"reply": "❌ Daily Message Limit Exceeded (50 chats)!"})

    # New Chat Title
    if not cid or cid == "null":
        cid = str(int(time.time()*1000))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))
    
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    
    # Vision & Memory enabled call
    reply = get_ai_response(msg, cid, user, img)
    
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    
    # Update Usage in DB
    today = datetime.now().strftime('%Y-%m-%d')
    if img:
        db.execute("UPDATE usage SET img_count = img_count + 1 WHERE user=? AND date=?", (user, today))
    else:
        db.execute("UPDATE usage SET msg_count = msg_count + 1 WHERE user=? AND date=?", (user, today))
    db.commit()
    
    new_msg_count, _ = get_daily_usage(user)
    return jsonify({"reply": reply, "chat_id": cid, "new_usage_count": new_msg_count})

@app.route("/chats")
def get_chats():
    if 'user' not in session: return jsonify([])
    rows = db.execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session['user'],)).fetchall()
    return jsonify(rows)

@app.route("/msgs")
def get_msgs():
    cid = request.args.get("c")
    rows = db.execute("SELECT role, content FROM messages WHERE chat_id=?", (cid,)).fetchall()
    return jsonify(rows)

@app.route("/delete_history", methods=["POST"])
def delete_history():
    user = session.get("user")
    db.execute("DELETE FROM chats WHERE user=?", (user,))
    db.execute("DELETE FROM messages WHERE chat_id NOT IN (SELECT id FROM chats)") # Clean orphans
    db.commit()
    return jsonify({"success": True})

# ================= UI HTML (Login Page) =================
UI_HTML_LOGIN = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI - Nihit Kr.</title>
    <style>
        body { background:#0a0a0a; color:white; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; font-family: sans-serif; }
        h1 { font-size: 50px; letter-spacing: -2px; color: #fff; margin-bottom: 10px;}
        p { color: #888; margin-bottom: 40px; font-size: 18px; }
        a { padding: 15px 30px; background: #fff; color: #000; text-decoration: none; border-radius: 50px; font-weight: bold; font-size: 18px; transition: 0.3s;}
        a:hover { background: #ccc; }
    </style>
</head>
<body>
    <h1>PERPLEX AI</h1>
    <p>Pro Coding, Memory & Vision. Created by Nihit kr.</p>
    <a href="/login">Login with Google</a>
</body>
</html>
"""

# ================= UI HTML (Main Chat + Pro UI) =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI V9 | Nihit Kr.</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root { --bg: #0d0d0d; --panel: #161616; --accent: #2563eb; --border: #222; --text: #ececec; }
        body { margin:0; background:var(--bg); color:var(--text); font-family: -apple-system, system-ui, sans-serif; display:flex; height:100vh; overflow:hidden; }
        
        /* Sidebar and Search */
        .sidebar { width:280px; background:var(--panel); border-right:1px solid var(--border); display:flex; flex-direction:column; padding:15px; position:relative; }
        .logo { font-size:18px; font-weight:bold; color:var(--accent); margin-bottom: 15px;}
        .new-chat { background:#2f2f2f; border:1px solid #333; color:white; padding:12px; border-radius:8px; width:100%; cursor:pointer; font-size:14px; margin-bottom:10px; }
        .search-box { position:relative; margin-bottom:10px; }
        .search-box input { width:93%; background:#0a0a0a; border:1px solid #222; color:white; padding:8px 10px; border-radius:6px; outline:none; font-size:13px; }
        .chat-list { flex:1; overflow-y:auto; margin-top:10px;}
        .chat-item { padding:10px; border-radius:8px; cursor:pointer; color:#b4b4b4; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:13.5px; }
        .chat-item:hover, .chat-item.active { background:#222; color:white; }
        
        /* Main Layout and Canvas */
        .main { flex:1; display:flex; position:relative; }
        .chat-area { flex:1; display:flex; flex-direction:column; border-right:1px solid var(--border); transition: 0.3s;}
        .chat-area.with-canvas { flex: 0.5; }
        
        /* Message Box */
        #box { flex:1; overflow-y:auto; padding:20px 10%; display:flex; flex-direction:column; gap:20px; }
        .msg { padding:12px 18px; border-radius:15px; max-width:85%; line-height:1.6; font-size:15px; word-wrap: break-word;}
        .user { align-self:flex-end; background:#2563eb; color:white; }
        .assistant { align-self:flex-start; background:#1e1e1e; border:1px solid #333; color:#ececec; }
        
        /* Canvas (Split Screen) */
        .canvas { width:50%; background:#000; border-left:1px solid var(--border); display:none; flex-direction:column; transition: 0.3s; animation: slideIn 0.3s;}
        @keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
        
        .canvas-header { padding:10px; background:#111; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); }
        #codeEditor { flex:1; background:#000; color:#4ade80; padding:20px; border:none; font-family: monospace; font-size:14px; outline:none; resize:none; overflow-y:auto; }
        #preview { width:100%; height:40%; background:white; border:none; }
        
        /* Input Area Pro */
        .input-wrap { padding:10px 10% 20px 10%; position:relative; }
        .limit-bar { position:absolute; top:-25px; left:10.5%; font-size:11px; color:#555; }
        .input-box { background:#1a1a1a; border:1px solid #333; border-radius:24px; padding:8px 15px; display:flex; align-items:center; gap:10px; box-shadow: 0 4px 15px rgba(0,0,0,0.5);}
        .plus-btn { color:#888; cursor:pointer; font-size:22px; position:relative; width:30px; text-align:center; }
        .plus-menu { position:absolute; bottom:60px; left:0; background:#1e1e1e; border:1px solid #333; border-radius:10px; display:none; flex-direction:column; min-width:160px; z-index:100;}
        .plus-menu div { padding:12px; font-size:14px; cursor:pointer; border-bottom:1px solid #333; }
        .plus-menu div:last-child { border:none; }
        .plus-menu div:hover { background:#2a2a2a; color:white; }
        
        input[type="text"] { flex:1; background:transparent; border:none; color:white; outline:none; font-size:16px; padding: 10px 0;}
        #sendBtn, #stopBtn { border:none; color:white; padding:10px 20px; border-radius:20px; cursor:pointer; font-weight:bold;}
        #sendBtn { background:#2563eb;}
        #stopBtn { background:#d32f2f; display:none;}
        
        /* Settings Panel */
        .settings-panel { position:fixed; top:70px; left:20px; background:#1e1e1e; padding:15px; border-radius:10px; width:200px; display:none; z-index:2000; border:1px solid #333;}
        .settings-item { cursor:pointer; color:#b4b4b4; padding:10px 0; font-size:14px;}
        .settings-item:hover { color:white;}
        
        /* Small fixes/tags */
        .vision-preview { display:none; padding:10px; background:#1a1a1a; margin-bottom:10px; border-radius:10px;}
        .vision-preview img { height:60px; border-radius:5px;}
        
        /* Removed "Nihit Kr. Edition" from sidebar bottom */
        .bottom-sidebar { position:absolute; bottom:15px; left:20px; }
        .logout-link { color: #ff4d4d; text-decoration: none; font-size: 14px; font-weight:bold; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">PERPLEX AI</div>
        <button class="new-chat" onclick="startNewChat()">+ New Chat</button>
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Search chats..." oninput="searchChats()">
        </div>
        <div class="chat-list" id="list"></div>
        
        <!-- Updated settings and removed text -->
        <span onclick="toggleSettings()" style="cursor:pointer; color:#555; position:absolute; bottom:50px; left:20px; font-size:14px;">⚙️ Settings</span>
        
        <div class="bottom-sidebar">
            <a href="/logout" class="logout-link">🚪 Logout</a>
        </div>
    </div>

    <div class="main">
        <div class="chat-area" id="chatArea">
            <div id="box"></div>
            <div class="input-wrap">
                <div class="limit-bar">Daily Limit: <span id="msgCountTag">{{msg_usage}}</span>/50 | Vision: <span id="imgCountTag">{{img_usage}}</span>/5</div>
                <div class="vision-preview" id="visionPreview"><span style="float:right; cursor:pointer;" onclick="clearVisionPreview()">✕</span><img id="prevImg"></div>
                
                <div class="input-box">
                    <div class="plus-btn" onclick="togglePlusMenu()">+
                        <div class="plus-menu" id="plusMenu">
                            <div onclick="openCanvasManual()">🎨 Open Canvas</div>
                            <div onclick="document.getElementById('fInput').click()">🖼️ Upload Photo/Video</div>
                        </div>
                    </div>
                    <input type="file" id="fInput" hidden accept="image/*,video/*" onchange="previewMedia(this)">
                    <input type="text" id="in" placeholder="Ask Nihit's AI..." onkeypress="if(event.key=='Enter')send()">
                    <button id="sendBtn" onclick="send()">Send</button>
                    <button id="stopBtn" onclick="stopAI()">Stop</button>
                </div>
            </div>
        </div>

        <div class="canvas" id="canvasArea">
            <div class="canvas-header">
                <span>Code Preview | Senior Dev. Mode</span>
                <div style="display:flex; gap:10px;">
                    <button onclick="runCode()" style="background:#22c55e; border:none; color:white; padding:5px 12px; border-radius:6px; cursor:pointer;">Run Code</button>
                    <span onclick="toggleCanvas()" style="color:#ff4b4b; cursor:pointer; font-weight:bold; font-size:18px;">✕</span>
                </div>
            </div>
            <textarea id="codeEditor" spellcheck="false"></textarea>
            <iframe id="preview"></iframe>
        </div>
    </div>

    <div class="settings-panel" id="settingsPanel">
        <div class="settings-item" style="color:red; font-weight:bold;" onclick="clearAllChat()">🗑️ Clear All Chat History</div>
        <div class="settings-item" onclick="alert(document.cookie)">🍪 View Cookies Preference</div>
        <div class="settings-item" onclick="toggleSettings()" style="color:#888;">Close</div>
    </div>

    <script>
        let currentCid = null;
        let selectedImg = null;
        let controller = null; // for stop response

        async function send() {
            const input = document.getElementById("in");
            const val = input.value.trim();
            if(!val && !selectedImg) return;

            const box = document.getElementById("box");
            box.innerHTML += `<div class="msg user">${val}</div>`;
            input.value = "";
            box.scrollTop = box.scrollHeight;
            
            toggleSendBtn(true); // switch to stop

            const fd = new FormData();
            fd.append("msg", val);
            fd.append("chat", currentCid);
            if(selectedImg) fd.append("image", selectedImg);

            controller = new AbortController();
            const signal = controller.signal;

            try {
                const r = await fetch("/send", {method:"POST", body:fd, signal});
                const d = await r.json();
                
                // Exceeded Limit Checks
                if(d.reply.includes("Limit Exceeded")) {
                    box.innerHTML += `<div class="msg assistant" style="color:#ff4d4d">${d.reply}</div>`;
                } else {
                    currentCid = d.chat_id;
                    updateUsageTags(d.new_usage_count);
                    handleAIResponse(d.reply);
                }
                
            } catch(err) {
                if(err.name === 'AbortError') box.innerHTML += `<div class="msg assistant" style="color:#888">*(Nihit AI: Response Stopped)*</div>`;
                else box.innerHTML += `<div class="msg assistant" style="color:#ff4d4d">*(Error: Server error)*</div>`;
            }

            toggleSendBtn(false); // switch back to send
            clearVisionPreview();
            loadHistory();
        }

        // --- CORE UI FUNCTIONS ---

        function handleAIResponse(reply) {
            const box = document.getElementById("box");
            const codeEditor = document.getElementById("codeEditor");
            
            // Pro Split Logic: Detect Large Code blocks (```html ... ```)
            const codeRegex = /```(html|css|javascript|json)?\s*([\s\S]*?)```/;
            const match = reply.match(codeRegex);

            if(match) {
                // Split Screen Activation like Gemini
                toggleCanvas(true);
                codeEditor.value = match[2].trim();
                
                // Show only text explanation in chat area
                const cleanText = reply.replace(/```(html|css|javascript|json)?\s*[\s\S]*?
```/g, "*(Developer: Large Code block sent to Canvas for preview)*");
                box.innerHTML += `<div class="msg assistant">${cleanText}</div>`;
            } else {
                box.innerHTML += `<div class="msg assistant">${reply.replace(/\\n/g, '<br>')}</div>`;
            }
            box.scrollTop = box.scrollHeight;
        }

        function runCode() {
            const code = document.getElementById("codeEditor").value;
            const frame = document.getElementById("preview").contentWindow.document;
            frame.open();
            frame.write(code);
            frame.close();
        }

        function toggleCanvas(forceShow = false) {
            const canvas = document.getElementById("canvasArea");
            const chatArea = document.getElementById("chatArea");
            if(forceShow || canvas.style.display === "none") {
                canvas.style.display = "flex";
                chatArea.classList.add("with-canvas");
            } else {
                canvas.style.display = "none";
                chatArea.classList.remove("with-canvas");
            }
        }
        function openCanvasManual() { toggleCanvas(true); togglePlusMenu(); }

        function toggleSendBtn(loading) {
            document.getElementById("sendBtn").style.display = loading ? "none" : "block";
            document.getElementById("stopBtn").style.display = loading ? "block" : "none";
        }
        function stopAI() { if(controller) controller.abort(); }

        // --- MEDIA FUNCTIONS ---

        function previewMedia(input) {
            const file = input.files[0];
            if(!file) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                selectedImg = e.target.result.split(',')[1]; // Base64 part
                document.getElementById("prevImg").src = e.target.result;
                document.getElementById("visionPreview").style.display = "block";
            };
            reader.readAsDataURL(file);
            togglePlusMenu();
        }
        function clearVisionPreview() { selectedImg = null; document.getElementById("visionPreview").style.display = "none"; }

        // --- CHAT FUNCTIONS ---

        function loadHistory() {
            fetch("/chats").then(r=>r.json()).then(data => {
                const l = document.getElementById("list"); l.innerHTML = "";
                data.forEach(c => {
                    const item = document.createElement("div");
                    item.className = `chat-item ${c[0] === currentCid ? 'active' : ''}`;
                    item.innerText = c[1];
                    item.onclick = () => openChat(c[0]);
                    l.appendChild(item);
                });
            });
        }
        function openChat(id) {
            currentCid = id;
            clearVisionPreview();
            toggleCanvas(false);
            fetch("/msgs?c="+id).then(r=>r.json()).then(msgs => {
                const box = document.getElementById("box"); box.innerHTML = "";
                msgs.forEach(m => {
                    // Re-process code blocks for Canvas if they exist
                    const content = m[1].includes("```") ? m[1].replace(/```[\s\S]*?```/g, "*(Developer: Code sent to Canvas)*") : m[1];
                    box.innerHTML += `<div class="msg ${m[0]}">${content}</div>`;
                });
                box.scrollTop = box.scrollHeight;
                loadHistory();
            });
        }
        function startNewChat() { location.reload(); }

        // --- MISC UI FUNCTIONS ---
        
        function searchChats() {
            const q = document.getElementById("searchInput").value.toLowerCase();
            document.querySelectorAll(".chat-item").forEach(item => {
                item.style.display = item.innerText.toLowerCase().includes(q) ? "block" : "none";
            });
        }
        function toggleSettings() { const s = document.getElementById("settingsPanel"); s.style.display = s.style.display === "block" ? "none" : "block"; }
        function togglePlusMenu() { const m = document.getElementById("plusMenu"); m.style.display = m.style.display === "flex" ? "none" : "flex"; }
        function updateUsageTags(msg_usage) { document.getElementById("u-count").innerText = msg_usage; } // updated by /send
        function clearAllChat() { if(confirm("Bhai, saari chat history delete kar dun? Sab khtm ho jayega!")) fetch("/delete_history", {method:"POST"}).then(()=>location.reload()); }

        loadHistory();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
