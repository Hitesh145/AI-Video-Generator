import { useEffect, useState } from "react";

type GenerationStage = { label: string; detail: string };
type VideoResponse = {
    lesson_request: { topic: string; audience: string; duration_minutes: number };
    lesson_plan: { title: string; learning_objectives: string[] };
    scene_durations: number[];
    video_path: string;
    audio_path: string | null;
    subtitle_path: string | null;
};
type LibraryVideo = { id: string; title: string; filename: string; url: string; created_at: number; size_bytes: number };

const stages: GenerationStage[] = [
    { label: "Gathering resources", detail: "Grounding the lesson in useful concepts" },
    { label: "Building the lesson plan", detail: "Organizing the explanation for your audience" },
    { label: "Creating the script", detail: "Writing narration with a clear teaching flow" },
    { label: "Designing scenes", detail: "Turning ideas into visual moments" },
    { label: "Rendering motion", detail: "Drawing frames and applying captions" },
    { label: "Adding narration", detail: "Generating voice audio and timing the scenes" },
    { label: "Assembling the video", detail: "Combining motion, sound, and subtitles" },
];

const API_URL = "http://localhost:8000/lesson/generate-demo-video";
const LIBRARY_URL = "http://localhost:8000/videos";
const MEDIA_URL = "http://localhost:8000";

function App() {
    const [request, setRequest] = useState("Explain binary search to a beginner.");
    const [activeStage, setActiveStage] = useState(-1);
    const [elapsedSeconds, setElapsedSeconds] = useState(0);
    const [isGenerating, setIsGenerating] = useState(false);
    const [result, setResult] = useState<VideoResponse | null>(null);
    const [library, setLibrary] = useState<LibraryVideo[]>([]);
    const [error, setError] = useState("");

    async function loadLibrary() {
        try {
            const response = await fetch(LIBRARY_URL);
            console.log("Library loaded:", response);
            if (response.ok) setLibrary((await response.json()) as LibraryVideo[]);
        } catch {
            // The generation studio remains usable while the library is unavailable.
            console.error("Failed to load library.");
        }
    }

    useEffect(() => {
        void loadLibrary();
    }, []);

    useEffect(() => {
        if (!isGenerating) return;
        const timer = window.setInterval(() => {
            setElapsedSeconds((seconds) => seconds + 1);
            setActiveStage((stage) => Math.min(stage + 1, stages.length - 1));
        }, 2600);
        return () => window.clearInterval(timer);
    }, [isGenerating]);

    async function generateVideo() {
        if (!request.trim() || isGenerating) return;
        setIsGenerating(true);
        setActiveStage(0);
        setElapsedSeconds(0);
        setResult(null);
        setError("");
        try {
            const response = await fetch(API_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ request: request.trim() }),
            });
            if (!response.ok) throw new Error((await response.text()) || `Generation failed with status ${response.status}`);
            setResult((await response.json()) as VideoResponse);
            setActiveStage(stages.length);
            void loadLibrary();
        } catch (generationError) {
            setError(generationError instanceof Error ? generationError.message : "Video generation failed.");
        } finally {
            setIsGenerating(false);
        }
    }

    const statusText = error ? "Generation stopped" : result ? "Your lesson is ready" : "The studio is working through each stage";

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
                    <section className={`progress-panel ${isGenerating || result ? "is-active" : ""}`} aria-live="polite">
                        <div className="panel-heading progress-heading"><span className="step-number">02</span><div><p className="panel-kicker">Production pipeline</p><h2>{statusText}</h2></div>{(isGenerating || result) && <span className="elapsed">{elapsedSeconds}s</span>}</div>
                        <div className="stage-list">{stages.map((stage, index) => { const complete = activeStage > index; const current = isGenerating && activeStage === index; return <div className={`stage ${complete ? "complete" : ""} ${current ? "current" : ""}`} key={stage.label}><span className="stage-icon">{complete ? "✓" : current ? <span className="loader-dot" /> : String(index + 1).padStart(2, "0")}</span><div><strong>{stage.label}</strong><small>{stage.detail}</small></div>{current && <span className="stage-state">working</span>}</div>; })}</div>
                    </section>
                </div>
                {result && <section className="result-panel"><div><p className="panel-kicker">Export complete</p><h2>{result.lesson_plan.title}</h2><p>{result.lesson_request.audience} lesson · {result.scene_durations.length} scenes · narrated video with subtitles</p></div><div className="result-badge">MP4 ready <span>✓</span></div></section>}
                <section className="library-section">
                    <div className="library-heading"><div><p className="eyebrow">Your archive</p><h2>Previous videos</h2></div><span>{library.length} {library.length === 1 ? "video" : "videos"}</span></div>
                    {library.length === 0 ? <p className="empty-library">Generated lessons will appear here for replay. </p> : <div className="library-grid">{library.map((video) => <article className="video-card" key={video.id}><video controls preload="metadata" src={`${MEDIA_URL}${video.url}`} /><div className="video-card-info"><h3>{video.title}</h3><p>{video.filename}</p></div></article>)}</div>}
                </section>
            </section>
            <footer className="footer"><span>EDUGEN AI</span><span>Plan · animate · explain</span></footer>
        </main>
    );
}

export default App;
