import os 

from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if api_key :
    print("API Key loaded successfully.")
    print(f"API Key: {api_key[0:4]}...{api_key[-4:]}")  # Print only the first and last 4 characters for security
else:
    print("API Key not found. Please check your .env file.")