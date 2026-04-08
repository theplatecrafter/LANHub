from flask import Blueprint, render_template
from glob_vars import CHAT_MAX_CHARS

chat_bp = Blueprint("chat", __name__)

@chat_bp.route("/chat")
def chat():
    return render_template("chat.html", MAX_CHARS=CHAT_MAX_CHARS)