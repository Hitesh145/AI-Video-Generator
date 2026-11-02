import { apiFetch } from "./api";
import { errorDetail } from "./papers";

export type CoverageLevel = "covered" | "weak" | "absent";
export type CoverageCheck = { level: CoverageLevel; best_similarity: number | null; message: string };
export type PaperVideo = { video_id: string; title: string; kind: "paper" | "general" | "topic"; url: string; created_at: string; notes: string[] };
export type StartMode = "paper" | "general";

export type StageState = "pending" | "current" | "done" | "failed";
export type JobStage = { key: string; label: string; state: StageState; detail: string | null };
export type JobStatus = {
    job_id: string;
    status: "running" | "completed" | "failed";
    elapsed_seconds: number;
    stages: JobStage[];
    error: { stage: string; message: string } | null;
};

export const MAX_TOPIC_LENGTH = 500;
const REFUSAL_MARKER = "does not address this topic";

/** A failed job's message for display, and whether it is the "paper does not cover this" refusal. */
export function describeJobFailure(error: { stage: string; message: string }): { text: string; refusal: boolean } {
    const refusal = error.message.includes(REFUSAL_MARKER);
    // The server prefixes the exception name ("TopicNotAddressed: ..."); a person should not see it.
    const message = error.message.replace(/^[A-Za-z]+:\s*/, "");
    return { text: refusal ? message : `${error.stage}: ${message}`, refusal };
}
export const JOB_POLL_INTERVAL_MS = 1000;
export const MAX_JOB_POLL_FAILURES = 5;

export const QUICK_TOPICS = [
    { label: "Summary", topic: "Give a summary of the whole paper" },
    { label: "Method", topic: "Explain the method this paper proposes" },
    { label: "Results", topic: "Explain the results this paper reports" },
    { label: "Limitations", topic: "Explain the limitations and future work this paper mentions" },
];

const base = (paperId: string) => `/papers/${encodeURIComponent(paperId)}/videos`;
const jsonPost = (body: unknown): RequestInit => ({
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
});

/** Throws an Error carrying the server's plain-language reason when the request is refused. */
export async function checkCoverage(paperId: string, topic: string): Promise<CoverageCheck> {
    const response = await apiFetch(`${base(paperId)}/check`, jsonPost({ topic }));
    if (!response.ok) throw new Error(await errorDetail(response, "Could not check this topic."));
    return (await response.json()) as CoverageCheck;
}

/** Starts the video and returns the job id to poll at /lesson/jobs/{id}. */
export async function startVideo(paperId: string, topic: string, mode: StartMode): Promise<string> {
    const response = await apiFetch(base(paperId), jsonPost({ topic, mode }));
    if (!response.ok) throw new Error(await errorDetail(response, "Could not start the video."));
    return ((await response.json()) as { job_id: string }).job_id;
}

export async function listVideos(paperId: string): Promise<PaperVideo[]> {
    const response = await apiFetch(base(paperId));
    if (!response.ok) throw new Error(await errorDetail(response, "Could not load the videos."));
    return (await response.json()) as PaperVideo[];
}

/** When polling stops without a final answer, show the pipeline as stopped instead of still working. */
export function markStopped(job: JobStatus | null): JobStatus | null {
    if (!job) return job;
    return { ...job, status: "failed", stages: job.stages.map((stage) => (stage.state === "current" ? { ...stage, state: "failed" } : stage)) };
}
