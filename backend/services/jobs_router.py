from fastapi import APIRouter, HTTPException

from schemas.job import JobCreated, JobStatus
from schemas.lesson import UserLessonRequest
from services.job_service import JobService


def create_jobs_router(job_service: JobService) -> APIRouter:
    router = APIRouter()

    @router.post("/lesson/jobs", response_model=JobCreated, status_code=202)
    def create_job(request: UserLessonRequest) -> JobCreated:
        return JobCreated(job_id=job_service.start(request))

    @router.get("/lesson/jobs/{job_id}", response_model=JobStatus)
    def get_job(job_id: str) -> JobStatus:
        status = job_service.get(job_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Unknown job")
        return status

    return router
