import google.generativeai as genai

# =========================================
# CONFIGURE API
# =========================================

genai.configure(
    api_key="AIzaSyBMn_-w8jrlWS5JCLc0jY8Rq7UkZhxrqk4"
)

# =========================================
# LOAD MODEL
# =========================================

model = genai.GenerativeModel(
    "models/gemini-2.5-flash"
)

# =========================================
# ASK AI
# =========================================

response = model.generate_content(
    "Fix this C code: int main( {"
)

# =========================================
# PRINT RESPONSE
# =========================================

print(response.text)