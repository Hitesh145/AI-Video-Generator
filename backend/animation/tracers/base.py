from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, Field

from animation.schemas import TraceStep


ArrayValue = Annotated[int, Field(ge=-99, le=999)]


class ArrayInput(BaseModel):
    values: list[ArrayValue] = Field(
        min_length=2,
        max_length=12,
        description="Array values; prefer 5-8 values so the animation stays readable.",
    )


class SearchInput(ArrayInput):
    target: ArrayValue = Field(description="Value to search for.")


class Tracer(Protocol):
    name: str
    description: str
    input_schema: type[BaseModel]
    template: Literal["array"]

    def trace(self, inputs: Any) -> list[TraceStep]:
        ...


class TracerRegistry:
    def __init__(self, tracers: list[Tracer] | None = None) -> None:
        self._tracers: dict[str, Tracer] = {}
        for tracer in tracers or []:
            self.register(tracer)

    def register(self, tracer: Tracer) -> None:
        if tracer.name in self._tracers:
            raise ValueError(f"Tracer already registered: {tracer.name}")
        self._tracers[tracer.name] = tracer

    def get(self, name: str) -> Tracer | None:
        return self._tracers.get(name)

    def names(self) -> list[str]:
        return list(self._tracers)

    def catalogue(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tracer.name,
                "description": tracer.description,
                "inputs_schema": tracer.input_schema.model_json_schema(),
            }
            for tracer in self._tracers.values()
        ]
