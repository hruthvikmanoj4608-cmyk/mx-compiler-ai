import os

from dotenv import load_dotenv

load_dotenv()

import google.generativeai as genai

from groq import Groq
from openai import OpenAI

# =========================================================
# GEMINI
# =========================================================

genai.configure(
    api_key=os.getenv("GEMINI_API_KEY")
)

gemini_model = genai.GenerativeModel(
    "gemini-1.5-flash"
)

# =========================================================
# GROQ
# =========================================================

groq_client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)

# =========================================================
# OPENROUTER
# =========================================================

openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

# =========================================================
# OPENAI
# =========================================================

openai_client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

# =========================================================
# GEMINI
# =========================================================

def ask_gemini(prompt):

    try:

        response = gemini_model.generate_content(
            prompt
        )

        text = getattr(response, "text", "")

        if not text:
            raise Exception("Empty Gemini response")

        return {
            "success": True,
            "provider": "Gemini",
            "response": text
        }

    except Exception as e:

        return {
            "success": False,
            "provider": "Gemini",
            "error": str(e)
        }

# =========================================================
# GROQ
# =========================================================

def ask_groq(prompt):

    try:

        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0
        )

        text = completion.choices[0].message.content

        if not text:
            raise Exception("Empty Groq response")

        return {
            "success": True,
            "provider": "Groq",
            "response": text
        }

    except Exception as e:

        return {
            "success": False,
            "provider": "Groq",
            "error": str(e)
        }

# =========================================================
# OPENROUTER
# =========================================================

def ask_openrouter(prompt):

    try:

        completion = openrouter_client.chat.completions.create(
            model="meta-llama/llama-3-8b-instruct:free",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0
        )

        text = completion.choices[0].message.content

        if not text:
            raise Exception("Empty OpenRouter response")

        return {
            "success": True,
            "provider": "OpenRouter",
            "response": text
        }

    except Exception as e:

        return {
            "success": False,
            "provider": "OpenRouter",
            "error": str(e)
        }

# =========================================================
# OPENAI
# =========================================================

def ask_openai(prompt):

    try:

        completion = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0
        )

        text = completion.choices[0].message.content

        if not text:
            raise Exception("Empty OpenAI response")

        return {
            "success": True,
            "provider": "OpenAI",
            "response": text
        }

    except Exception as e:

        return {
            "success": False,
            "provider": "OpenAI",
            "error": str(e)
        }

# =========================================================
# MAIN AI ROUTER
# =========================================================

def ask_ai(prompt):

    providers = [
        ask_gemini,
        ask_groq,
        ask_openrouter,
        ask_openai
    ]

    last_error = None

    for provider in providers:

        result = provider(prompt)

        if result["success"]:
            return result

        last_error = result

    return last_error