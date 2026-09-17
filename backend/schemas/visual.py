from typing import Any

from pydantic import BaseModel, Field, model_validator


class VisualElement(BaseModel):
    id: str = Field(
        description="Unique identifier for this visual element within the scene."
    )
    type: str = Field(
        description=(
            "Semantic role of the element, such as concept, input, output, "
            "equation, label, arrow, object, or data_structure."
        )
    )
    description: str = Field(
        description="What this element represents educationally."
    )
    label: str | None = Field(
        default=None,
        description="Optional short text label that may be shown to the learner.",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional structured educational data for this element. This should "
            "describe meaning, not low-level rendering details."
        ),
    )


class VisualRelationship(BaseModel):
    type: str = Field(
        description=(
            "Semantic relationship between elements, such as causes, contains, "
            "flows_to, compares_with, part_of, or transforms_into."
        )
    )
    source: str = Field(
        description="ID of the source visual element."
    )
    target: str = Field(
        description="ID of the target visual element."
    )
    description: str = Field(
        description="Educational meaning of this relationship."
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured data describing the relationship.",
    )


class VisualAction(BaseModel):
    order: int = Field(
        ge=1,
        description="One-based sequence order of the action within the scene.",
    )
    type: str = Field(
        description=(
            "Semantic action, such as show, hide, highlight, compare, connect, "
            "transform, move, annotate, or reveal."
        )
    )
    target: list[str] = Field(
        min_length=1,
        description="IDs of the visual elements affected by this action.",
    )
    description: str = Field(
        description="What educational change should happen."
    )
    narration_cue: str | None = Field(
        default=None,
        description=(
            "Optional phrase or idea in the narration that should trigger this "
            "action during later synchronization."
        ),
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional structured action data. This should stay renderer-neutral."
        ),
    )


class VisualScene(BaseModel):
    id: str = Field(
        description="Unique identifier for the scene."
    )
    section_title: str = Field(
        description="Exact lesson-script section title supported by this scene."
    )
    narration_reference: str = Field(
        description=(
            "Stable reference to the narration block this scene supports, such "
            "as introduction, conclusion, or script_section_2."
        )
    )
    purpose: str = Field(
        description="The educational purpose of this scene."
    )
    visual_type: str = Field(
        description=(
            "Broad representation category, such as diagram, animation, chart, "
            "equation, timeline, process, comparison, graph, map, text, "
            "illustration, or mixed."
        )
    )
    description: str = Field(
        description="Renderer-neutral description of what the learner should see."
    )
    layout: str | None = Field(
        default=None,
        description=(
            "Optional high-level composition, such as left-to-right flow or "
            "side-by-side comparison. Avoid pixel coordinates or tool-specific "
            "instructions."
        ),
    )
    elements: list[VisualElement] = Field(
        min_length=1,
        description="Semantic visual elements appearing in the scene.",
    )
    relationships: list[VisualRelationship] = Field(
        default_factory=list,
        description="Semantic relationships among scene elements.",
    )
    actions: list[VisualAction] = Field(
        min_length=1,
        description="Ordered semantic visual actions occurring in the scene.",
    )
    duration_seconds: float = Field(
        gt=0,
        description="Estimated duration of the scene in seconds.",
    )

    @model_validator(mode="after")
    def validate_references(self) -> "VisualScene":
        element_ids = {element.id for element in self.elements}

        for relationship in self.relationships:
            if relationship.source not in element_ids:
                raise ValueError(
                    f"Relationship source '{relationship.source}' is not a scene element."
                )
            if relationship.target not in element_ids:
                raise ValueError(
                    f"Relationship target '{relationship.target}' is not a scene element."
                )

        for action in self.actions:
            missing_targets = [
                target for target in action.target if target not in element_ids
            ]
            if missing_targets:
                missing = ", ".join(missing_targets)
                raise ValueError(
                    f"Action '{action.type}' references unknown target(s): {missing}."
                )

        action_orders = [action.order for action in self.actions]
        if len(action_orders) != len(set(action_orders)):
            raise ValueError("Visual actions must have unique order values.")

        return self


class ScenePlan(BaseModel):
    scenes: list[VisualScene] = Field(
        description="Ordered sequence of educational visual scenes."
    )
