from typing import Literal

from pydantic import BaseModel

from schemas.demo import DemoVideoResponse


StageState = Literal["pending", "current", "done", "failed"]


class JobStage(BaseModel):
    key: str
    label: str
    state: StageState
    detail: str | None = None


class JobSection(BaseModel):
    index: int
    total: int
    title: str
    path: str
    activity: str


class JobError(BaseModel):
    stage: str
    message: str


class JobStatus(BaseModel):
    job_id: str
    status: Literal["running", "completed", "failed"]
    elapsed_seconds: float
    stages: list[JobStage]
    section: JobSection | None = None
    result: DemoVideoResponse | None = None
    error: JobError | None = None


class JobCreated(BaseModel):
    job_id: str
