from animation.schemas import ArrayState, TraceStep
from animation.tracers.base import SearchInput


class LinearSearchTracer:
    name = "linear_search"
    description = (
        "Linear search: check each element from left to right until the target "
        "is found or the array ends."
    )
    input_schema = SearchInput
    template = "array"

    def trace(self, inputs: SearchInput) -> list[TraceStep]:
        values = list(inputs.values)
        target = inputs.target
        steps = [
            TraceStep(
                state=ArrayState(values=values),
                event=f"Search for {target} by checking each value from left to right.",
            )
        ]

        for index, value in enumerate(values):
            if value == target:
                steps.append(
                    TraceStep(
                        state=ArrayState(
                            values=values,
                            pointers={"i": index},
                            dimmed=list(range(index)),
                            found=index,
                        ),
                        event=f"values[{index}] = {target}. Found the target at index {index}.",
                    )
                )
                return steps

            steps.append(
                TraceStep(
                    state=ArrayState(
                        values=values,
                        pointers={"i": index},
                        highlighted=[index],
                        dimmed=list(range(index)),
                    ),
                    event=f"values[{index}] = {value}, which is not {target}. Move on.",
                )
            )

        steps.append(
            TraceStep(
                state=ArrayState(values=values, dimmed=list(range(len(values)))),
                event=f"Every value has been checked, so {target} is not in the array.",
            )
        )
        return steps
