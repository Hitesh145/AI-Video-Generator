from animation.schemas import ArrayState, TraceStep
from animation.tracers.base import ArrayInput


class InsertionSortTracer:
    name = "insertion_sort"
    description = (
        "Insertion sort: grow a sorted part on the left by taking the next value "
        "and moving it left until it is in place."
    )
    input_schema = ArrayInput
    template = "array"

    def trace(self, inputs: ArrayInput) -> list[TraceStep]:
        values = list(inputs.values)
        steps = [
            TraceStep(
                state=ArrayState(values=list(values), sorted_indices=[0]),
                event="The first value on its own is already sorted.",
            )
        ]

        for i in range(1, len(values)):
            key = values[i]
            steps.append(
                TraceStep(
                    state=ArrayState(
                        values=list(values),
                        pointers={"key": i},
                        highlighted=[i],
                        sorted_indices=list(range(i)),
                    ),
                    event=f"Take {key} and insert it into the sorted part on the left.",
                )
            )

            j = i
            while j > 0 and values[j - 1] > values[j]:
                values[j - 1], values[j] = values[j], values[j - 1]
                steps.append(
                    TraceStep(
                        state=ArrayState(
                            values=list(values),
                            pointers={"key": j - 1},
                            highlighted=[j - 1],
                            sorted_indices=list(range(i)),
                            swapped=(j - 1, j),
                        ),
                        event=f"{values[j]} is bigger than {key}, so {key} moves left.",
                    )
                )
                j -= 1

            steps.append(
                TraceStep(
                    state=ArrayState(values=list(values), sorted_indices=list(range(i + 1))),
                    event=f"{key} is in place. The first {i + 1} values are sorted.",
                )
            )

        return steps
