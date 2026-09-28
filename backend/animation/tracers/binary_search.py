from pydantic import model_validator

from animation.schemas import ArrayState, TraceStep
from animation.tracers.base import SearchInput


class BinarySearchInput(SearchInput):
    @model_validator(mode="after")
    def _values_sorted(self) -> "BinarySearchInput":
        if any(a > b for a, b in zip(self.values, self.values[1:])):
            raise ValueError("Binary search needs values sorted in ascending order.")
        return self


class BinarySearchTracer:
    name = "binary_search"
    description = (
        "Binary search for a target in a sorted array: compare the middle element "
        "and discard the half that cannot contain the target."
    )
    input_schema = BinarySearchInput
    template = "array"

    def trace(self, inputs: BinarySearchInput) -> list[TraceStep]:
        values = list(inputs.values)
        target = inputs.target
        lo, hi = 0, len(values) - 1
        dimmed: set[int] = set()

        steps = [
            TraceStep(
                state=ArrayState(values=values, pointers={"lo": lo, "hi": hi}),
                event=f"Search for {target}. The whole array is in range: lo = {lo}, hi = {hi}.",
            )
        ]

        while lo <= hi:
            mid = (lo + hi) // 2
            value = values[mid]
            steps.append(
                TraceStep(
                    state=ArrayState(
                        values=values,
                        pointers={"lo": lo, "mid": mid, "hi": hi},
                        highlighted=[mid],
                        dimmed=sorted(dimmed),
                    ),
                    event=f"mid = ({lo} + {hi}) // 2 = {mid}. Compare values[{mid}] = {value} with {target}.",
                )
            )

            if value == target:
                steps.append(
                    TraceStep(
                        state=ArrayState(
                            values=values,
                            pointers={"mid": mid},
                            dimmed=sorted(dimmed),
                            found=mid,
                        ),
                        event=f"values[{mid}] = {target}. Found the target at index {mid}.",
                    )
                )
                return steps

            if value < target:
                dimmed.update(range(lo, mid + 1))
                event = (
                    f"{value} < {target}, so the target can only be to the right. "
                    f"Rule out indices {lo} to {mid}."
                )
                lo = mid + 1
            else:
                dimmed.update(range(mid, hi + 1))
                event = (
                    f"{value} > {target}, so the target can only be to the left. "
                    f"Rule out indices {mid} to {hi}."
                )
                hi = mid - 1

            pointers = {"lo": lo, "hi": hi} if lo <= hi else {}
            steps.append(
                TraceStep(
                    state=ArrayState(values=values, pointers=pointers, dimmed=sorted(dimmed)),
                    event=event,
                )
            )

        steps.append(
            TraceStep(
                state=ArrayState(values=values, dimmed=sorted(dimmed)),
                event=f"The search range is empty, so {target} is not in the array.",
            )
        )
        return steps
