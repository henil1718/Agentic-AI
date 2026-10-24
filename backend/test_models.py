import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

models = client.models.list()
print("Your allowed Groq models:")
for m in models.data:
    print(f"- {m.id}")