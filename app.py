from flask import Flask, render_template, request
from flask_socketio import SocketIO
from dotenv import load_dotenv

from ai_router import ask_ai

import subprocess
import os
import uuid
import time
import signal
import shutil
import pty
import select
import resource
import threading
import json
import re

from concurrent.futures import ThreadPoolExecutor

# =========================================================
# LOAD ENV
# =========================================================

load_dotenv()

# =========================================================
# APP SETUP
# =========================================================

app = Flask(__name__)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=10 * 1024 * 1024
)

# =========================================================
# GLOBAL SETTINGS
# =========================================================

BASE_DIR = "mx_sessions"

os.makedirs(BASE_DIR, exist_ok=True)

MAX_WORKERS = 10

MAX_OUTPUT_SIZE = 5 * 1024 * 1024

MAX_EXECUTION_TIME = 120

INACTIVITY_TIMEOUT = 300

MAX_CODE_SIZE = 200000

MEMORY_LIMIT = 512 * 1024 * 1024

executor = ThreadPoolExecutor(
    max_workers=MAX_WORKERS
)

# =========================================================
# ANSI CLEANER
# =========================================================

ANSI_ESCAPE = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')

# =========================================================
# ACTIVE SESSIONS
# =========================================================

active_sessions = {}

session_lock = threading.Lock()

# =========================================================
# HOME PAGE
# =========================================================

@app.route("/")
def home():
    return render_template("live.html")

# =========================================================
# PROCESS LIMITS
# =========================================================

def set_process_limits():

    try:

        resource.setrlimit(
            resource.RLIMIT_CPU,
            (
                MAX_EXECUTION_TIME,
                MAX_EXECUTION_TIME
            )
        )

        resource.setrlimit(
            resource.RLIMIT_AS,
            (
                MEMORY_LIMIT,
                MEMORY_LIMIT
            )
        )

    except:
        pass

# =========================================================
# PREEXEC
# =========================================================

def preexec_function():

    os.setsid()

    set_process_limits()

# =========================================================
# CLEANUP SESSION
# =========================================================

def cleanup_session(sid):

    with session_lock:

        session = active_sessions.get(sid)

        if not session:
            return

        proc = session.get("proc")

        master_fd = session.get("master_fd")

        session_dir = session.get("session_dir")

        try:

            if proc and proc.poll() is None:

                try:

                    os.killpg(
                        os.getpgid(proc.pid),
                        signal.SIGKILL
                    )

                except:

                    proc.kill()

        except:
            pass

        try:

            if master_fd is not None:

                os.close(master_fd)

        except:
            pass

        active_sessions.pop(sid, None)

    try:

        if session_dir and os.path.exists(session_dir):

            shutil.rmtree(session_dir)

    except:
        pass

# =========================================================
# AI ANALYZER
# =========================================================

def analyze_code_with_ai(code, gcc_error):

    prompt = f"""
You are an expert beginner-friendly C programming teacher.

A student wrote C code.

Your job:
1. Read FULL student code.
2. Understand GCC compilation errors.
3. Fix ONLY compilation-related mistakes.
4. Preserve student coding style and structure.
5. Do NOT rewrite the entire program differently.
6. Return ONLY valid JSON.
7. Explain errors in simple beginner language.

Return JSON EXACTLY in this format:

{{
  "errors": [
    {{
      "line": 0,
      "wrong": "",
      "reason": "",
      "correct": ""
    }}
  ],
  "corrected_code": ""
}}

Student Code:
{code}

GCC Error:
{gcc_error}
"""

    result = ask_ai(prompt)

    if not result["success"]:

        return {
            "errors": [
                {
                    "line": 0,
                    "wrong": "AI Analysis Failed",
                    "reason": result.get("error", "Unknown Error"),
                    "correct": "Please try again"
                }
            ],
            "corrected_code": code,
            "provider": result.get("provider", "Unknown")
        }

    try:

        content = result["response"]

        content = content.strip()

        if content.startswith("```"):

            content = re.sub(r'^```(?:json)?', '', content)
            content = re.sub(r'```$', '', content)
            content = content.strip()

        parsed = json.loads(content)

        parsed["provider"] = result["provider"]

        return parsed

    except Exception as error:

        return {
            "errors": [
                {
                    "line": 0,
                    "wrong": "Invalid AI JSON Response",
                    "reason": str(error),
                    "correct": "Retry analysis"
                }
            ],
            "corrected_code": code,
            "provider": result.get("provider", "Unknown")
        }

# =========================================================
# STREAM OUTPUT
# =========================================================

def stream_output(sid, proc, master_fd):

    total_output = 0

    try:

        while True:

            with session_lock:

                if sid not in active_sessions:
                    return

            ready, _, _ = select.select(
                [master_fd],
                [],
                [],
                0.05
            )

            if ready:

                try:

                    data = os.read(
                        master_fd,
                        4096
                    ).decode(
                        errors="ignore"
                    )

                    if data:

                        data = ANSI_ESCAPE.sub('', data)

                        total_output += len(
                            data.encode()
                        )

                        if total_output > MAX_OUTPUT_SIZE:

                            socketio.emit(
                                "output",
                                {
                                    "data": "\n\n⚠️ Output Limit Exceeded\n"
                                },
                                room=sid
                            )

                            cleanup_session(sid)

                            return

                        socketio.emit(
                            "output",
                            {"data": data},
                            room=sid
                        )

                except:
                    pass

            if proc.poll() is not None:
                break

    except:
        pass

    socketio.emit(
        "output",
        {
            "data": "\n\n🏁 Program Finished.\n"
        },
        room=sid
    )

    cleanup_session(sid)

# =========================================================
# TIMEOUT WATCHER
# =========================================================

def timeout_watcher(sid):

    while True:

        time.sleep(1)

        with session_lock:

            session = active_sessions.get(sid)

            if not session:
                return

            proc = session["proc"]

            if proc.poll() is not None:
                return

            last_activity = session["last_activity"]

            start_time = session["start_time"]

        if (
            time.time() - last_activity
            > INACTIVITY_TIMEOUT
        ):

            socketio.emit(
                "output",
                {
                    "data": "\n\n⏰ Program Stopped Due To Inactivity\n"
                },
                room=sid
            )

            cleanup_session(sid)

            return

        if (
            time.time() - start_time
            > MAX_EXECUTION_TIME
        ):

            socketio.emit(
                "output",
                {
                    "data": "\n\n⏰ Maximum Execution Time Reached\n"
                },
                room=sid
            )

            cleanup_session(sid)

            return

# =========================================================
# COMPILE AND RUN
# =========================================================

def compile_and_run(sid, code):

    cleanup_session(sid)

    if len(code) > MAX_CODE_SIZE:

        socketio.emit(
            "output",
            {
                "data": "\n❌ Code Size Too Large\n"
            },
            room=sid
        )

        return

    blocked_keywords = [
        "fork",
        "vfork",
        "system",
        "popen",
        "execl",
        "execv",
        "kill",
        "unlink",
        "remove",
        "rmdir"
    ]

    lower_code = code.lower()

    for keyword in blocked_keywords:

        if keyword in lower_code:

            socketio.emit(
                "output",
                {
                    "data": f"\n⚠️ Restricted Function: {keyword}\n"
                },
                room=sid
            )

            return

    unique_id = str(uuid.uuid4())

    session_dir = os.path.abspath(
        os.path.join(
            BASE_DIR,
            unique_id
        )
    )

    os.makedirs(session_dir)

    c_file = os.path.join(
        session_dir,
        "main.c"
    )

    exe_name = "program.out"

    exe_file = os.path.join(
        session_dir,
        exe_name
    )

    with open(c_file, "w", encoding="utf-8") as file:

        file.write(code)

    start_compile = time.time()

    compile_process = subprocess.run(
        [
            "gcc",
            c_file,
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-lm",
            "-o",
            exe_file
        ],
        capture_output=True,
        text=True
    )

    compile_time = round(
        time.time() - start_compile,
        2
    )

    # =====================================================
    # AI ERROR HANDLING
    # =====================================================

    if compile_process.returncode != 0:

        socketio.emit(
            "output",
            {
                "data": "\n❌ Compilation Error Detected\n\n🤖 AI Analyzing Code...\n"
            },
            room=sid
        )

        ai_result = analyze_code_with_ai(
            code,
            compile_process.stderr
        )

        socketio.emit(
            "ai_error",
            ai_result,
            room=sid
        )

        cleanup_session(sid)

        return

    if not os.path.exists(exe_file):

        socketio.emit(
            "output",
            {
                "data": "\n❌ Executable Creation Failed\n"
            },
            room=sid
        )

        cleanup_session(sid)

        return

    try:

        master_fd, slave_fd = pty.openpty()

        proc = subprocess.Popen(
            [f"./{exe_name}"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=session_dir,
            preexec_fn=preexec_function,
            close_fds=True
        )

        os.close(slave_fd)

        with session_lock:

            active_sessions[sid] = {
                "proc": proc,
                "master_fd": master_fd,
                "session_dir": session_dir,
                "start_time": time.time(),
                "last_activity": time.time()
            }

        socketio.emit(
            "output",
            {
                "data": f"✅ Compilation Successful ({compile_time}s)\n🚀 MX CompileX Starting...\n\n"
            },
            room=sid
        )

        socketio.start_background_task(
            stream_output,
            sid,
            proc,
            master_fd
        )

        socketio.start_background_task(
            timeout_watcher,
            sid
        )

    except Exception as error:

        socketio.emit(
            "output",
            {
                "data": f"\n❌ Runtime Error\n\n{str(error)}\n"
            },
            room=sid
        )

        cleanup_session(sid)

# =========================================================
# START SESSION
# =========================================================

@socketio.on("start_session")
def start_program(data):

    sid = request.sid

    code = data.get("code", "")

    executor.submit(
        compile_and_run,
        sid,
        code
    )

# =========================================================
# TERMINAL INPUT
# =========================================================

@socketio.on("terminal_input")
def terminal_input(data):

    sid = request.sid

    with session_lock:

        session = active_sessions.get(sid)

        if not session:
            return

        master_fd = session["master_fd"]

        session["last_activity"] = time.time()

    try:

        user_input = data.get("data", "")

        os.write(
            master_fd,
            (user_input + "\n").encode()
        )

    except:
        pass

# =========================================================
# STOP PROGRAM
# =========================================================

@socketio.on("stop_program")
def stop_program():

    sid = request.sid

    socketio.emit(
        "output",
        {
            "data": "\n\n🛑 Program Stopped By User\n"
        },
        room=sid
    )

    cleanup_session(sid)

# =========================================================
# DISCONNECT
# =========================================================

@socketio.on("disconnect")
def disconnect():

    cleanup_session(request.sid)

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    socketio.run(
        app,
        host="0.0.0.0",
        port=5001,
        debug=False,
        allow_unsafe_werkzeug=True
    )