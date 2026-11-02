import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiFetch } from "./api";
import {
    JOB_POLL_INTERVAL_MS,
    MAX_JOB_POLL_FAILURES,
    MAX_TOPIC_LENGTH,
    QUICK_TOPICS,
    checkCoverage,
    listVideos,
    markStopped,
    startVideo,
    type CoverageCheck,
    type JobStatus,
    type PaperVideo,
    type StartMode,
} from "./paperVideoApi";

function PaperVideos({ paperId, ready }: { paperId: string; ready: boolean }) {
    const [topic, setTopic] = useState("");
    const [busy, setBusy] = useState(false);               // checking or starting
    const [popup, setPopup] = useState<CoverageCheck | null>(null);
    const [jobId, setJobId] = useState<string | null>(null);
    const [job, setJob] = useState<JobStatus | null>(null);
    const [error, setError] = useState("");
    const [videos, setVideos] = useState<PaperVideo[]>([]);

    const running = busy || jobId !== null;
    const trimmed = topic.trim();

    const loadVideos = useCallback(async () => {
        try {
            setVideos(await listVideos(paperId));
        } catch {
            // The panel stays usable if the list cannot be loaded right now.
            console.error("Failed to load the paper's videos.");
        }
    }, [paperId]);

    useEffect(() => {
        void loadVideos();
    }, [loadVideos]);

    // Follows the running job with the same rules as the studio page.
    useEffect(() => {
        if (!jobId) return;
        let cancelled = false;
        let failures = 0;
        let timer = 0;

        const poll = async () => {
            try {
                const response = await apiFetch(`/lesson/jobs/${jobId}`);
                if (response.status === 404) {
                    if (!cancelled) {
                        setError("The server no longer knows this job (it may have restarted). Please generate again.");
                        setJob(markStopped);
                        setJobId(null);
                    }
                    return;
                }
                if (!response.ok) throw new Error(`Status ${response.status}`);
                const status = (await response.json()) as JobStatus;
                failures = 0;
                if (cancelled) return;
                setJob(status);
                if (status.status !== "running") {
                    if (status.status === "failed" && status.error) setError(`${status.error.stage}: ${status.error.message}`);
                    setJobId(null);
                    void loadVideos();
                    return;
                }
            } catch {
                failures += 1;
                if (failures >= MAX_JOB_POLL_FAILURES) {
                    if (!cancelled) {
                        setError("Lost connection to the server.");
                        setJob(markStopped);
                        setJobId(null);
                    }
                    return;
                }
            }
            if (!cancelled) timer = window.setTimeout(poll, JOB_POLL_INTERVAL_MS);
        };

        timer = window.setTimeout(poll, 0);
        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [jobId, loadVideos]);

    async function start(mode: StartMode) {
        setPopup(null);
        setBusy(true);
        setError("");
        setJob(null);
        try {
            setJobId(await startVideo(paperId, trimmed, mode));
        } catch (startError) {
            setError(startError instanceof Error ? startError.message : "Could not start the video.");
        } finally {
            setBusy(false);
        }
    }

    async function generate() {
        if (!ready || !trimmed || running) return;
        setBusy(true);
        setError("");
        setJob(null);
        try {
            const check = await checkCoverage(paperId, trimmed);
            setBusy(false);
            if (check.level === "covered") await start("paper");
            else setPopup(check);
        } catch (checkError) {
            setBusy(false);
            setError(checkError instanceof Error ? checkError.message : "Could not check this topic.");
        }
    }

    const elapsed = Math.round(job?.elapsed_seconds ?? 0);

    return (
        <>
            <section className="report-section paper-videos">
                <p className="eyebrow">Ask for a video</p>
                <h2>What should the video explain?</h2>
                {!ready ? (
                    <p className="empty-library">Videos can be made once the paper is ready.</p>
                ) : (
                    <>
                        <div className="quick-topics">
                            {QUICK_TOPICS.map((quick) => (
                                <button key={quick.label} type="button" className="quick-topic" disabled={running} onClick={() => setTopic(quick.topic)}>{quick.label}</button>
                            ))}
                        </div>
                        <textarea
                            className="topic-box"
                            value={topic}
                            maxLength={MAX_TOPIC_LENGTH}
                            disabled={running}
                            placeholder="Or type any topic from this paper"
                            aria-label="Video topic"
                            onChange={(event) => setTopic(event.target.value)}
                        />
                        <div className="prompt-footer">
                            <span className="hint">The video uses only passages of this paper.</span>
                            <button className="generate-button" onClick={() => void generate()} disabled={running || !trimmed}>
                                {running ? "Working..." : "Generate video"}<span aria-hidden="true">↗</span>
                            </button>
                        </div>
                    </>
                )}
                {error && <p className="error-message">{error}</p>}
                {job && (
                    <div className="stage-list" aria-live="polite">
                        {job.stages.map((stage, index) => (
                            <div className={`stage ${stage.state === "done" ? "complete" : ""} ${stage.state === "current" ? "current" : ""} ${stage.state === "failed" ? "failed" : ""}`} key={stage.key}>
                                <span className="stage-icon">{stage.state === "done" ? "✓" : stage.state === "failed" ? "!" : stage.state === "current" ? <span className="loader-dot" /> : String(index + 1).padStart(2, "0")}</span>
                                <div><strong>{stage.label}</strong><small>{stage.detail ?? ""}</small></div>
                                {stage.state === "current" && <span className="stage-state">working</span>}
                            </div>
                        ))}
                        <p className="hint">{elapsed}s</p>
                    </div>
                )}
            </section>

            {popup && (
                <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Topic coverage">
                    <div className="modal">
                        <h2>{popup.level === "weak" ? "The paper may only mention this" : "The paper does not cover this"}</h2>
                        <p>{popup.message}</p>
                        <div className="modal-actions">
                            {popup.level === "weak" && <button className="generate-button" onClick={() => void start("paper")}>Short video of what the paper says</button>}
                            <button className="generate-button" onClick={() => void start("general")}>Normal video, not from the paper</button>
                            <button className="link-button" onClick={() => setPopup(null)}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}

            <section className="library-section">
                <div className="library-heading"><div><p className="eyebrow">From this paper</p><h2>Videos</h2></div><span>{videos.length} {videos.length === 1 ? "video" : "videos"}</span></div>
                {videos.length === 0 ? (
                    <p className="empty-library">No videos yet.</p>
                ) : (
                    <div className="library-grid">
                        {videos.map((video) => (
                            <article className="video-card" key={video.video_id}>
                                <video controls preload="metadata" src={`${API_BASE}${video.url}`} />
                                <div className="video-card-info">
                                    <h3>{video.title}</h3>
                                    <p>{video.kind === "paper" ? "From the paper" : "Not from the paper"}</p>
                                    {video.kind === "paper" && <p className="video-note">Not yet checked sentence by sentence against the paper.</p>}
                                </div>
                            </article>
                        ))}
                    </div>
                )}
            </section>
        </>
    );
}

export default PaperVideos;
