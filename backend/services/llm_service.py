import os 

from dotenv import load_dotenv
from google import genai
from typing import TypeVar
from pydantic import BaseModel


load_dotenv()

T = TypeVar("T", bound=BaseModel)


class LLMService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        model = os.getenv("GEMINI_MODEL")

        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables. Please check your .env file.")
        if not model:
            raise ValueError("GEMINI_MODEL not found in environment variables. Please check your .env file.")

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def generate(self , prompt : str ) -> str:
        response = self.client.interactions.create(
            model = self.model,
            input=  prompt,
        )

        if not response.output_text :
            raise ValueError("No response text received from the model.")

        return response.output_text

    def generate_structured(self,prompt: str,response_schema: type[T],) -> T:
        interaction = self.client.interactions.create(
        model=self.model,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": response_schema.model_json_schema(),
        },
    )

        if not interaction.output_text:
            raise RuntimeError("Gemini returned an empty response.")

        return response_schema.model_validate_json(interaction.output_text)