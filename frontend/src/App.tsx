import { useCallback, useEffect, useState } from "react";

type StageState = "pending" | "current" | "done" | "failed";
type JobStage = { key: string; label: string; state: StageState; detail: string | null };
type SectionSummary = {
    title: string;
    path_used: "trace" | "codegen" | "slideshow";
    tracer: string | null;
    duration_seconds: number;
    warnings: string[];
};
type VideoResponse = {
    lesson_request: { topic: string; audience: string; duration_minutes: number };
    lesson_plan: { title: string; learning_objectives: string[] };
    scene_durations: number[];
    video_path: string;
    video_url: string | null;
    audio_path: string | null;
    subtitle_path: string | null;
    sections: SectionSummary[];
};
type JobStatus = {
    job_id: string;
    status: "running" | "completed" | "failed";
    elapsed_seconds: number;
    stages: JobStage[];
    section: { index: number; total: number; title: string; path: string; activity: string } | null;
    result: VideoResponse | null;
    error: { stage: string; message: string } | null;
};
type LibraryVideo = { id: string; title: string; filename: string; url: string; created_at: number; size_bytes: number };

const API_BASE = "http://localhost:8000";
const JOBS_URL = `${API_BASE}/lesson/jobs`;
const LIBRARY_URL = `${API_BASE}/videos`;
const POLL_INTERVAL_MS = 1000;
const MAX_POLL_FAILURES = 5;

function pathLabel(section: SectionSummary): string {
    if (section.path_used === "trace") return `Algorithm trace · ${section.tracer ?? "unknown"}`;
    if (section.path_used === "codegen") return "Custom animation";
    return "Slideshow fallback";
}

function App() {
    const [request, setRequest] = useState("Explain binary search to a beginner.");
    const [jobId, setJobId] = useState<string | null>(null);
    const [job, setJob] = useState<JobStatus | null>(null);
    const [isStarting, setIsStarting] = useState(false);
    const [library, setLibrary] = useState<LibraryVideo[]>([]);
    const [error, setError] = useState("");

    const isGenerating = isStarting || jobId !== null;
    const result = job?.status === "completed" ? job.result : null;

    const loadLibrary = useCallback(async () => {
        try {
            const response = await fetch(LIBRARY_URL);
            if (response.ok) setLibrary((await response.json()) as LibraryVideo[]);
        } catch {
            // The generation studio remains usable while the library is unavailable.
            console.error("Failed to load library.");
        }
    }, []);

    useEffect(() => {
        void loadLibrary();
    }, [loadLibrary]);

    useEffect(() => {
        if (!jobId) return;
        let cancelled = false;
        let failures = 0;
        let timer = 0;

        const poll = async () => {
            try {
                const response = await fetch(`${JOBS_URL}/${jobId}`);
                if (!response.ok) throw new Error(`Status ${response.status}`);
                const status = (await response.json()) as JobStatus;
                failures = 0;
                if (cancelled) return;
                setJob(status);
                if (status.status !== "running") {
                    if (status.status === "failed" && status.error) setError(`${status.error.stage}: ${status.error.message}`);
                    setJobId(null);
                    void loadLibrary();
                    return;
                }
            } catch {
                failures += 1;
                if (failures >= MAX_POLL_FAILURES) {
                    if (!cancelled) {
                        setError("Lost connection to the server.");
                        setJobId(null);
                    }
                    return;
                }
            }
            if (!cancelled) timer = window.setTimeout(poll, POLL_INTERVAL_MS);
        };

        timer = window.setTimeout(poll, 0);
        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [jobId, loadLibrary]);

    async function generateVideo() {
        if (!request.trim() || isGenerating) return;
        setIsStarting(true);
        setJob(null);
        setError("");
        try {
            const response = await fetch(JOBS_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ request: request.trim() }),
            });
            if (!response.ok) throw new Error((await response.text()) || `Could not start generation (status ${response.status})`);
            const created = (await response.json()) as { job_id: string };
            setJobId(created.job_id);
        } catch (generationError) {
            setError(generationError instanceof Error ? generationError.message : "Video generation failed.");
        } finally {
            setIsStarting(false);
        }
    }

    const statusText = error ? "Generation stopped" : result ? "Your lesson is ready" : job || isGenerating ? "The studio is working through each stage" : "Ready when you are";
    const elapsed = Math.round(job?.elapsed_seconds ?? 0);

    return (
        <main className="app-shell">
            <header className="topbar"><div className="brand-mark"><span>EDU</span><strong>GEN</strong></div><div className="topbar-status"><span className="status-dot" /> Video studio <span className="slash">/</span> beta</div></header>
            <section className="workspace">
                <div className="intro"><p className="eyebrow">Motion lesson studio</p><h1>Turn a question into a <em>visual explanation.</em></h1><p className="intro-copy">Describe what you want to teach. EduGen will plan the lesson, choreograph the scenes, and assemble a narrated video.</p></div>
                <div className="studio-grid">
                    <section className="prompt-panel">
                        <div className="panel-heading"><span className="step-number">01</span><div><p className="panel-kicker">Your lesson</p><h2>What should we explain?</h2></div></div>
                        <textarea value={request} onChange={(event) => setRequest(event.target.value)} disabled={isGenerating} aria-label="Lesson request" />
                        <div className="prompt-footer"><span className="hint">Try a concept, process, or algorithm</span><button className="generate-button" onClick={generateVideo} disabled={isGenerating || !request.trim()}>{isGenerating ? "Generating..." : "Generate video"}<span aria-hidden="true">↗</span></button></div>
                        {error && <p className="error-message">{error}</p>}
                    </section>
                    <section className={`progress-panel ${isGenerating || job ? "is-active" : ""}`} aria-live="polite">
                        <div className="panel-heading progress-heading"><span className="step-number">02</span><div><p className="panel-kicker">Production pipeline</p><h2>{statusText}</h2></div>{(isGenerating || job) && <span className="elapsed">{elapsed}s</span>}</div>
                        {job ? (
                            <div className="stage-list">{job.stages.map((stage, index) => <div className={`stage ${stage.state === "done" ? "complete" : ""} ${stage.state === "current" ? "current" : ""} ${stage.state === "failed" ? "failed" : ""}`} key={stage.key}><span className="stage-icon">{stage.state === "done" ? "✓" : stage.state === "failed" ? "!" : stage.state === "current" ? <span className="loader-dot" /> : String(index + 1).padStart(2, "0")}</span><div><strong>{stage.label}</strong><small>{stage.detail ?? ""}</small></div>{stage.state === "current" && <span className="stage-state">working</span>}</div>)}</div>
                        ) : (
                            <p className="stage-hint">{isGenerating ? "Starting the pipeline..." : "The real stages of the pipeline appear here once generation starts."}</p>
                        )}
                    </section>
                </div>
                {result && <section className="result-panel"><div><p className="panel-kicker">Export complete</p><h2>{result.lesson_plan.title}</h2><p>{result.lesson_request.audience} lesson · {result.sections.length} sections · narrated video with subtitles</p>{result.sections.length > 0 && <ul className="section-list">{result.sections.map((section, index) => <li key={`${index}-${section.title}`}><span className="section-title">{section.title}</span><span className={`path-badge path-${section.path_used}`}>{pathLabel(section)}</span></li>)}</ul>}</div><div className="result-badge">MP4 ready <span>✓</span></div>{result.video_url && <><video className="result-video" controls preload="metadata" src={`${API_BASE}${result.video_url}`} /><a className="result-link" href={`${API_BASE}${result.video_url}`} download>Download MP4</a></>}</section>}
                <section className="library-section">
                    <div className="library-heading"><div><p className="eyebrow">Your archive</p><h2>Previous videos</h2></div><span>{library.length} {library.length === 1 ? "video" : "videos"}</span></div>
                    {library.length === 0 ? <p className="empty-library">Generated lessons will appear here for replay. </p> : <div className="library-grid">{library.map((video) => <article className="video-card" key={video.id}><video controls preload="metadata" src={`${API_BASE}${video.url}`} /><div className="video-card-info"><h3>{video.title}</h3><p>{video.filename}</p></div></article>)}</div>}
                </section>
            </section>
            <footer className="footer"><span>EDUGEN AI</span><span>Plan · animate · explain</span></footer>
        </main>
    );
}

export default App;
