from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
import sqlite3, time, requests, json, base64, os
from datetime import timedelta, datetime

app = Flask(__name__)
app.secret_key = "nihit_kr_anur_canvas_key"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect("chat.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS usage_limits(user TEXT, date TEXT, msg_count INTEGER, img_count INTEGER, PRIMARY KEY(user, date))")
    conn.commit()
    return conn

db = init_db()

# ================= GOOGLE AUTH =================
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    access_token_url="https://oauth2.googleapis.com/token",
    authorize_url="https://accounts.google.com/o/oauth2/auth",
    api_base_url="https://www.googleapis.com/oauth2/v2/",
    client_kwargs={"scope": "email profile"}
)

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return '<body style="background:#0e0e0e; color:white; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; font-family:sans-serif;"><h1>Perplex AI</h1><a href="/login" style="padding:12px 24px; background:#2563eb; color:white; text-decoration:none; border-radius:30px; font-weight:bold;">Continue with Google</a></body>'

@app.route("/login")
def login(): return google.authorize_redirect("http://127.0.0.1:5000/callback")

@app.route("/callback")
def callback():
    token = google.authorize_access_token()
    user = google.get("userinfo").json()
    session["user"] = user["email"]
    return redirect("/chat")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ================= AI ENGINE (VISION SUPPORT) =================
OPENROUTER_KEY =os.getenv("OPENROUTER_KEY")

def get_ai_response(msg, base64_image=None):
    try:
        headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
        content_list = [{"type": "text", "text": msg}]
        
        if base64_image:
            if "base64," in base64_image:
                base64_data = base64_image.split("base64,")[1]
                mime_type = base64_image.split(":")[1].split(";")[0]
            else:
                base64_data = base64_image
                mime_type = "image/jpeg"
            content_list.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_data}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [
                {
                    "role": "system", 
                    "content": "Your name is Perplex AI. Created by Nihit kr. When someone asks who made you, always answer Nihit kr. You can see images and write code perfectly."
                },
                {"role": "user", "content": content_list}
            ]
        }
        
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error: {str(e)}"

# ================= ROUTES =================
@app.route("/chat")
def chat():
    if "user" not in session: return redirect("/")
    return UI_HTML

@app.route("/chats")
def get_chats():
    rows = db.execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session["user"],)).fetchall()
    return jsonify(rows)

@app.route("/msgs")
def get_msgs():
    cid = request.args.get("c")
    rows = db.execute("SELECT role, content FROM messages WHERE chat_id=?", (cid,)).fetchall()
    return jsonify(rows)

@app.route("/send", methods=["POST"])
def send_msg():
    user = session["user"]
    today = datetime.now().strftime('%Y-%m-%d')
    cid = request.form.get("chat")
    msg = request.form.get("msg")
    img_data = request.form.get("image")

    res = db.execute("SELECT msg_count, img_count FROM usage_limits WHERE user=? AND date=?", (user, today)).fetchone()
    m_count, i_count = (res[0], res[1]) if res else (0, 0)

    if m_count >= 50: return jsonify({"error": "Daily limit reached (50/50)"})
    if img_data and i_count >= 5: return jsonify({"error": "limit_over"})

    if not cid or cid == "null" or cid == "":
        cid = str(int(time.time()*1000))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))

    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    reply = get_ai_response(msg, img_data)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "ai", reply))
    
    db.execute("INSERT OR REPLACE INTO usage_limits VALUES(?,?,?,?)", (user, today, m_count+1, i_count + (1 if img_data else 0)))
    db.commit()
    
    return jsonify({"reply": reply, "chat_id": cid, "usage": m_count+1})

# ================= UPDATED UI =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root { --bg: #131314; --side: #1e1f20; --active: #333537; --text: #e3e3e3; --blue: #8ab4f8; --red: #ff6b6b; --border: #333; }
        body{margin:0; display:flex; height:100vh; background:var(--bg); color:var(--text); font-family:sans-serif; overflow:hidden;}
        
        /* Sidebar */
        .sidebar{width:260px; background:var(--side); padding:15px; display:flex; flex-direction:column; border-right:1px solid var(--border); transition: 0.3s;}
        .new-btn{background:#2a2b2d; padding:12px; border-radius:30px; text-align:center; cursor:pointer; margin-bottom:15px; font-weight:bold; border:1px solid #444;}
        .search-bar{background:#131314; border:1px solid #444; border-radius:10px; padding:8px 12px; margin-bottom:15px; display:flex; align-items:center;}
        .search-bar input{background:transparent; border:none; color:white; font-size:13px; width:100%; outline:none;}
        .chat-list{flex:1; overflow-y:auto; scrollbar-width:none;}
        .chat-item{padding:10px 15px; margin:4px 0; border-radius:20px; cursor:pointer; font-size:14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
        .chat-item:hover, .chat-item.active{background:var(--active);}
        
        /* Settings Button */
        .settings-btn{margin-top:auto; padding:12px; border-radius:10px; cursor:pointer; display:flex; align-items:center; gap:10px; font-size:14px; color:#aaa;}
        .settings-btn:hover{background:var(--active); color:white;}

        /* Main Section */
        .main-section{ flex:1; display:flex; flex-direction:column; background:var(--bg); position: relative; }
        .msgs{flex:1; overflow-y:auto; padding:20px 15%; display:flex; flex-direction:column; gap:25px; scroll-behavior: smooth;}
        .msg{max-width:90%; line-height:1.6; font-size:16px; word-wrap: break-word;}
        .user{align-self:flex-end; background:#2a2b2d; padding:12px 20px; border-radius:22px;}
        .ai{align-self:flex-start; white-space:pre-wrap;}
        .img-msg{max-width:300px; border-radius:10px; margin-top:10px;}

        /* Input Bar */
        .input-container{padding:15px 15%; display:flex; flex-direction:column; align-items:center; gap:8px; border-top: 1px solid var(--border);}
        .input-bar{width:100%; max-width:850px; background:#1e1f20; border-radius:35px; padding:8px 20px; display:flex; align-items:center; border:1px solid #444;}
        input#userInput{flex:1; background:transparent; border:none; color:white; padding:12px; outline:none; font-size:16px;}
        .icon-btn{background:transparent; border:none; color:#aaa; cursor:pointer; font-size:20px; padding:5px; margin:0 5px;}
        .icon-btn:hover{color:white;}
        .recording { color: var(--red) !important; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
        
        .attachment-preview{display:none; align-items:center; gap:10px; background:#2a2b2d; padding:8px 15px; border-radius:15px; margin-bottom:10px; border:1px solid var(--blue);}
        .attachment-preview img{height:40px; border-radius:5px;}
        .error-msg{color:var(--red); font-size:12px; font-weight:bold; display:none; margin-bottom:5px;}
        
        .usage-bar{padding:8px 20px; font-size:12px; color:#777; display:flex; justify-content:space-between; position: absolute; top: 0; width: 100%; box-sizing: border-box;}
        .disclaimer{font-size:11px; color:#555; margin-top:5px; text-align:center;}
    </style>
</head>
<body>

<div class="sidebar">
    <div class="new-btn" onclick="startFresh()">+ New Chat</div>
    <div class="search-bar"><span>🔍</span><input type="text" id="sidebarSearch" placeholder="Search chats..." oninput="searchChats()"></div>
    <div class="chat-list" id="chatList"></div>
    
    <div class="settings-btn" onclick="alert('Cookies Preferences: All Managed.')">
        <span>⚙️</span> Settings
    </div>
</div>

<div class="main-section">
    <div class="usage-bar">
        <span id="usageStat">Usage: 0/50</span>
        <span>Perplex AI</span>
    </div>

    <div class="msgs" id="chatBox">
        <div id="welcome" style="text-align:center; margin-top:20vh; opacity:0.5;">
            <h1 style="font-size: 40px;">Hello, I'm Perplex</h1>
            <p>I can help you with code, images, and more.</p>
        </div>
    </div>

    <div class="input-container">
        <div id="limitError" class="error-msg">Daily limit exceeded</div>
        <div class="attachment-preview" id="attachPreview">
            <img id="prevImg" src=""><button onclick="clearAttachment()" style="background:none; border:none; color:var(--red); cursor:pointer;">✕</button>
        </div>
        <div class="input-bar">
            <button class="icon-btn" title="Upload" onclick="document.getElementById('fileInput').click()">+</button>
            <input id="userInput" placeholder="Type a message..." onkeypress="if(event.key=='Enter')send()">
            <button class="icon-btn" id="micBtn" title="Voice" onclick="toggleVoice()">🎙️</button>
            <button class="icon-btn" id="sendBtn" onclick="send()" style="color:var(--blue);">➤</button>
        </div>
        <div class="disclaimer">Perplex is AI and can make mistakes</div>
    </div>
</div>

<input type="file" id="fileInput" hidden accept="image/*" onchange="previewFile(this)">

<script>
    let activeChatId = "";
    let currentBase64 = null;
    let isRecording = false;
    let recognition;

    // Speech Recognition Setup
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'en-US';

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            document.getElementById("userInput").value = transcript;
            stopVoice();
        };

        recognition.onerror = () => stopVoice();
        recognition.onend = () => stopVoice();
    }

    function toggleVoice() {
        if (!recognition) {
            alert("Voice recognition not supported in this browser.");
            return;
        }
        if (isRecording) stopVoice();
        else startVoice();
    }

    function startVoice() {
        isRecording = true;
        document.getElementById("micBtn").classList.add("recording");
        recognition.start();
    }

    function stopVoice() {
        isRecording = false;
        document.getElementById("micBtn").classList.remove("recording");
        if (recognition) recognition.stop();
    }

    function previewFile(input) {
        if(input.files && input.files[0]) {
            const reader = new FileReader();
            reader.onload = (e) => {
                currentBase64 = e.target.result;
                document.getElementById("prevImg").src = currentBase64;
                document.getElementById("attachPreview").style.display = 'flex';
            };
            reader.readAsDataURL(input.files[0]);
        }
    }

    function clearAttachment() {
        currentBase64 = null;
        document.getElementById("attachPreview").style.display = 'none';
        document.getElementById("fileInput").value = "";
    }

    function send() {
        const input = document.getElementById("userInput");
        const val = input.value.trim();
        if(!val && !currentBase64) return;

        const box = document.getElementById("chatBox");
        if(document.getElementById("welcome")) box.innerHTML = "";

        let userMsg = `<div class="msg user">`;
        if(currentBase64) userMsg += `<img src="${currentBase64}" class="img-msg"><br>`;
        userMsg += `${val}</div>`;
        box.innerHTML += userMsg;
        
        const text = val;
        input.value = "";
        box.scrollTop = box.scrollHeight;

        const fd = new FormData();
        fd.append("chat", activeChatId);
        fd.append("msg", text);
        if(currentBase64) fd.append("image", currentBase64);

        document.getElementById("sendBtn").innerText = "⌛";

        fetch("/send", {method:"POST", body:fd}).then(r=>r.json()).then(data => {
            document.getElementById("sendBtn").innerText = "➤";
            if(data.error) {
                alert(data.error);
                return;
            }
            activeChatId = data.chat_id;
            box.innerHTML += `<div class="msg ai">${data.reply}</div>`;
            box.scrollTop = box.scrollHeight;
            document.getElementById("usageStat").innerText = `Usage: ${data.usage}/50`;
            clearAttachment();
            loadChatList();
        });
    }

    function loadChatList() {
        fetch("/chats").then(r=>r.json()).then(data => {
            const list = document.getElementById("chatList");
            list.innerHTML = "";
            data.forEach(c => {
                const item = document.createElement("div");
                item.className = `chat-item ${c[0]==activeChatId?'active':''}`;
                item.innerText = c[1];
                item.onclick = () => openChat(c[0]);
                list.appendChild(item);
            });
        });
    }

    function openChat(id) {
        activeChatId = id;
        fetch("/msgs?c="+id).then(r=>r.json()).then(msgs => {
            const box = document.getElementById("chatBox");
            box.innerHTML = "";
            msgs.forEach(m => {
                box.innerHTML += `<div class="msg ${m[0]}">${m[1]}</div>`;
            });
            box.scrollTop = box.scrollHeight;
            loadChatList();
        });
    }

    function startFresh() {
        activeChatId = "";
        document.getElementById("chatBox").innerHTML = '<div id="welcome" style="text-align:center; margin-top:20vh; opacity:0.5;"><h1>Perplex AI</h1><p>I was created by Nihit kr.</p></div>';
        loadChatList();
    }

    loadChatList();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True)
