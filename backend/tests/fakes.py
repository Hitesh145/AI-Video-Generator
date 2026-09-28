from pydantic import BaseModel


class FakeLLM:
    """Returns queued responses in order; records every prompt."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate_structured(self, prompt: str, response_schema: type[BaseModel]) -> BaseModel:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("FakeLLM ran out of responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, BaseModel):
            return response
        return response_schema.model_validate(response)
