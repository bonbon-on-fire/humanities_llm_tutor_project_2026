"""
Flask web app for the Humanities LLM Tutor.
Allows chatting with the tutor and generating student bot messages.
"""

import os
import sys
import uuid
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from flask import Flask, jsonify, render_template, request, session
from langchain_core.messages import AIMessage, HumanMessage

from tutor.run_tutor import _create_tutor_graph, get_tutor_reply, load_system_prompt
from students.chaotic_student.student_01.bot import (
    get_next_student_message as chaotic_get_next,
)
from students.chitchat_student.student_01.bot import (
    get_next_student_message as chitchat_get_next,
)
from students.clueless_student.student_01.bot import (
    get_next_student_message as clueless_get_next,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")

# Build tutor graph once at startup
_system_prompt = load_system_prompt()
_tutor_graph = _create_tutor_graph(_system_prompt)

# In-memory store: session_id -> list[{"role": "student"|"tutor", "content": str}]
_conversations: dict[str, list] = {}

STUDENT_FNS = {
    "chaotic": chaotic_get_next,
    "chitchat": chitchat_get_next,
    "clueless": clueless_get_next,
}

STUDENT_LABELS = {
    "chaotic": "⚡ Chaotic student",
    "chitchat": "💬 Chitchat student",
    "clueless": "🤷 Clueless student",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_conv() -> list:
    """Return the current conversation list (creates session if needed)."""
    sid = session.get("sid")
    if not sid or sid not in _conversations:
        sid = str(uuid.uuid4())
        session["sid"] = sid
        _conversations[sid] = []
    return _conversations[sid]


def _set_conv(conv: list) -> None:
    _conversations[session["sid"]] = conv


def _to_tutor_msgs(conv: list) -> list:
    """Convert stored conversation to tutor-perspective LangChain messages.
    Student messages → HumanMessage, tutor messages → AIMessage.
    """
    result = []
    for m in conv:
        if m["role"] == "student":
            result.append(HumanMessage(content=m["content"]))
        else:
            result.append(AIMessage(content=m["content"]))
    return result


def _to_student_msgs(conv: list) -> list:
    """Convert stored conversation to student-perspective LangChain messages.
    Tutor messages → HumanMessage, student messages → AIMessage.
    """
    result = []
    for m in conv:
        if m["role"] == "tutor":
            result.append(HumanMessage(content=m["content"]))
        else:
            result.append(AIMessage(content=m["content"]))
    return result


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html", student_labels=STUDENT_LABELS)


@app.route("/reset", methods=["POST"])
def reset():
    """Clear conversation and get the tutor's opening message."""
    conv = _get_conv()
    conv.clear()

    # Seed with a neutral student opening so the tutor can greet properly
    seed = [HumanMessage(content="Hello, I'd like to get started on my assignment.")]
    _, tutor_text = get_tutor_reply(seed, graph=_tutor_graph)

    conv.append({"role": "tutor", "content": tutor_text})
    _set_conv(conv)
    return jsonify({"tutor": tutor_text})


@app.route("/chat", methods=["POST"])
def chat():
    """Receive a user-typed message, forward to tutor, return reply."""
    data = request.get_json(silent=True) or {}
    user_msg = data.get("message", "").strip()
    if not user_msg:
        return jsonify({"error": "Empty message."}), 400

    conv = _get_conv()
    conv.append({"role": "student", "content": user_msg})

    tutor_msgs = _to_tutor_msgs(conv)
    _, tutor_text = get_tutor_reply(tutor_msgs, graph=_tutor_graph)

    conv.append({"role": "tutor", "content": tutor_text})
    _set_conv(conv)

    return jsonify({"student": user_msg, "tutor": tutor_text})


@app.route("/student/<student_type>", methods=["POST"])
def student(student_type: str):
    """Generate a student-bot message then get the tutor's reply."""
    if student_type not in STUDENT_FNS:
        return jsonify({"error": f"Unknown student type: {student_type}"}), 400

    conv = _get_conv()
    if not conv or conv[-1]["role"] != "tutor":
        return jsonify({"error": "A tutor message must be the last in the conversation."}), 400

    student_msgs = _to_student_msgs(conv)
    bot_msg = STUDENT_FNS[student_type](student_msgs)
    student_text = bot_msg.content if isinstance(bot_msg.content, str) else str(bot_msg.content)

    conv.append({"role": "student", "content": student_text})

    tutor_msgs = _to_tutor_msgs(conv)
    _, tutor_text = get_tutor_reply(tutor_msgs, graph=_tutor_graph)

    conv.append({"role": "tutor", "content": tutor_text})
    _set_conv(conv)

    return jsonify({"student": student_text, "tutor": tutor_text})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
