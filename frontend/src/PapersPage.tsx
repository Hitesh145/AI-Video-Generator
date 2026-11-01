import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { apiFetch } from "./api";
import {
    MAX_POLL_FAILURES,
    MAX_UPLOAD_MB,
    POLL_INTERVAL_MS,
    STATUS_LABELS,
    errorDetail,
    formatSize,
    isInProgress,
    type Paper,
} from "./papers";

function PapersPage() {
    const [papers, setPapers] = useState<Paper[]>([]);
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");
    const [uploading, setUploading] = useState(false);
    const [retrying, setRetrying] = useState<string | null>(null);
    const [dragging, setDragging] = useState(false);
    const [reloadToken, setReloadToken] = useState(0);
    const fileInput = useRef<HTMLInputElement>(null);

    // Loads the library, and keeps refreshing every 2 s for as long as any paper is still being read.
    useEffect(() => {
        let cancelled = false;
        let failures = 0;
        let timer = 0;

        const tick = async () => {
            try {
                const response = await apiFetch("/papers");
                if (!response.ok) throw new Error(`Status ${response.status}`);
                const list = (await response.json()) as Paper[];
                failures = 0;
                if (cancelled) return;
                setPapers(list);
                setLoaded(true);
                if (!list.some((paper) => isInProgress(paper.status))) return;
            } catch {
                failures += 1;
                if (failures >= MAX_POLL_FAILURES) {
                    if (!cancelled) setError("Lost connection to the server.");
                    return;
                }
            }
            if (!cancelled) timer = window.setTimeout(tick, POLL_INTERVAL_MS);
        };

        timer = window.setTimeout(tick, 0);
        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [reloadToken]);

    async function upload(file: File) {
        if (uploading) return;           // a second drop while one is in flight is ignored
        setError("");
        setNotice("");
        if (!file.name.toLowerCase().endsWith(".pdf")) {
            setError("Only PDF files can be added.");
            return;
        }
        if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
            setError(`That file is larger than the ${MAX_UPLOAD_MB} MB limit.`);
            return;
        }
        setUploading(true);
        try {
            const body = new FormData();
            body.append("file", file);
            const response = await apiFetch("/papers", { method: "POST", body });
            if (!response.ok) {
                setError(await errorDetail(response, "The upload failed."));
                return;
            }
            if (response.status === 200) setNotice("You already added this paper.");
            setReloadToken((token) => token + 1);
        } catch {
            setError("Could not reach the server. Is the backend running?");
        } finally {
            setUploading(false);
        }
    }

    async function retry(paperId: string) {
        if (retrying) return;
        setRetrying(paperId);
        setError("");
        try {
            const response = await apiFetch(`/papers/${paperId}/retry`, { method: "POST" });
            if (!response.ok) setError(await errorDetail(response, "Could not retry this paper."));
            setReloadToken((token) => token + 1);
        } catch {
            setError("Could not reach the server. Is the backend running?");
        } finally {
            setRetrying(null);
        }
    }

    function onPick(event: ChangeEvent<HTMLInputElement>) {
        const file = event.target.files?.[0];
        event.target.value = "";           // lets the same file be chosen again later
        if (file) void upload(file);
    }

    function onDrop(event: DragEvent<HTMLLabelElement>) {
        event.preventDefault();
        setDragging(false);
        const file = event.dataTransfer.files[0];
        if (file) void upload(file);
    }

    return (
        <section className="workspace">
            <div className="intro"><p className="eyebrow">Research papers</p><h1>Paper videos</h1><p className="intro-copy">Add a research paper and EduGen reads it, so videos can explain it accurately. Papers are private to your account.</p></div>
            <label
                className={`upload-box ${dragging ? "dragging" : ""}`}
                onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
            >
                <input ref={fileInput} type="file" accept=".pdf,application/pdf" hidden onChange={onPick} disabled={uploading} />
                <strong>{uploading ? "Uploading..." : "Add a research paper"}</strong>
                <span>Drop a PDF here or click to choose one (up to {MAX_UPLOAD_MB} MB)</span>
            </label>
            {error && <p className="error-message">{error}</p>}
            {notice && <p className="notice-message">{notice}</p>}
            <section className="library-section">
                <div className="library-heading"><div><p className="eyebrow">Your library</p><h2>Papers</h2></div><span>{papers.length} {papers.length === 1 ? "paper" : "papers"}</span></div>
                {loaded && papers.length === 0 && <p className="empty-library">Add a research paper to get started.</p>}
                <ul className="paper-list">
                    {papers.map((paper) => (
                        <li className="paper-row" key={paper.paper_id}>
                            <div className="paper-main">
                                {paper.status === "ready"
                                    ? <a className="paper-title" href={`#/papers/${paper.paper_id}`}>{paper.title ?? paper.filename}</a>
                                    : <span className="paper-title">{paper.title ?? paper.filename}</span>}
                                <small>{formatSize(paper.size_bytes)}{paper.page_count ? ` · ${paper.page_count} pages` : ""}</small>
                                {paper.detail && <small className={`paper-detail ${paper.status === "failed" ? "failed" : ""}`}>{paper.detail}</small>}
                            </div>
                            <span className={`status-chip status-${paper.status}`}>{STATUS_LABELS[paper.status] ?? paper.status}</span>
                            {paper.can_retry && <button className="link-button" disabled={retrying !== null} onClick={() => void retry(paper.paper_id)}>Retry</button>}
                        </li>
                    ))}
                </ul>
            </section>
        </section>
    );
}

export default PapersPage;
