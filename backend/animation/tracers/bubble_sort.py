from animation.schemas import ArrayState, TraceStep
from animation.tracers.base import ArrayInput


class BubbleSortTracer:
    name = "bubble_sort"
    description = (
        "Bubble sort: compare neighbouring values and swap them when out of order, "
        "so the largest remaining value bubbles to the end on each pass."
    )
    input_schema = ArrayInput
    template = "array"

    def trace(self, inputs: ArrayInput) -> list[TraceStep]:
        values = list(inputs.values)
        count = len(values)
        done: set[int] = set()
        steps = [
            TraceStep(
                state=ArrayState(values=list(values)),
                event="Sort the array by comparing neighbouring values and swapping them when they are out of order.",
            )
        ]

        for end in range(count - 1, 0, -1):
            swapped_any = False
            for j in range(end):
                steps.append(
                    TraceStep(
                        state=ArrayState(
                            values=list(values),
                            pointers={"j": j},
                            highlighted=[j, j + 1],
                            sorted_indices=sorted(done),
                        ),
                        event=f"Compare {values[j]} and {values[j + 1]}.",
                    )
                )
                if values[j] > values[j + 1]:
                    values[j], values[j + 1] = values[j + 1], values[j]
                    swapped_any = True
                    steps.append(
                        TraceStep(
                            state=ArrayState(
                                values=list(values),
                                pointers={"j": j},
                                highlighted=[j, j + 1],
                                sorted_indices=sorted(done),
                                swapped=(j, j + 1),
                            ),
                            event=f"{values[j + 1]} is bigger than {values[j]}, so swap them.",
                        )
                    )

            done.add(end)
            if not swapped_any:
                steps.append(
                    TraceStep(
                        state=ArrayState(values=list(values), sorted_indices=list(range(count))),
                        event="No swaps in this pass, so the array is already sorted.",
                    )
                )
                return steps

            steps.append(
                TraceStep(
                    state=ArrayState(values=list(values), sorted_indices=sorted(done)),
                    event=f"{values[end]} has reached its final position at index {end}.",
                )
            )

        steps.append(
            TraceStep(
                state=ArrayState(values=list(values), sorted_indices=list(range(count))),
                event="The array is sorted.",
            )
        )
        return steps
