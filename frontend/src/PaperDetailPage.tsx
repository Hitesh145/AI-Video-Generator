import { useEffect, useState } from "react";
import { apiFetch } from "./api";
import {
    MAX_POLL_FAILURES,
    POLL_INTERVAL_MS,
    STATUS_LABELS,
    errorDetail,
    formatSize,
    isInProgress,
    type PaperDetail,
} from "./papers";

type Load = { kind: "loading" } | { kind: "missing" } | { kind: "error"; message: string } | { kind: "ready"; paper: PaperDetail };

function PaperDetailPage({ paperId }: { paperId: string }) {
    const [load, setLoad] = useState<Load>({ kind: "loading" });
    const [reloadToken, setReloadToken] = useState(0);
    const [retryError, setRetryError] = useState("");
    const [retrying, setRetrying] = useState(false);

    // Fetches the paper, and keeps refreshing every 2 s while it is still being read.
    useEffect(() => {
        let cancelled = false;
        let failures = 0;
        let timer = 0;

        const tick = async () => {
            try {
                const response = await apiFetch(`/papers/${encodeURIComponent(paperId)}`);
                if (response.status === 404) {
                    if (!cancelled) setLoad({ kind: "missing" });
                    return;
                }
                if (!response.ok) throw new Error(`Status ${response.status}`);
                const paper = (await response.json()) as PaperDetail;
                failures = 0;
                if (cancelled) return;
                setLoad({ kind: "ready", paper });
                if (!isInProgress(paper.status)) return;
            } catch {
                failures += 1;
                if (failures >= MAX_POLL_FAILURES) {
                    if (!cancelled) setLoad({ kind: "error", message: "Lost connection to the server." });
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
    }, [paperId, reloadToken]);

    async function retry() {
        if (retrying) return;
        setRetrying(true);
        setRetryError("");
        try {
            const response = await apiFetch(`/papers/${encodeURIComponent(paperId)}/retry`, { method: "POST" });
            if (!response.ok) setRetryError(await errorDetail(response, "Could not retry this paper."));
            setReloadToken((token) => token + 1);
        } catch {
            setRetryError("Could not reach the server. Is the backend running?");
        } finally {
            setRetrying(false);
        }
    }

    if (load.kind === "loading") {
        return <section className="workspace"><p className="empty-library">Loading...</p></section>;
    }
    if (load.kind === "missing") {
        return (
            <section className="workspace">
                <div className="intro"><p className="eyebrow">Research paper</p><h1>Paper not found</h1><p className="intro-copy">This paper does not exist, or it belongs to another account.</p><p><a className="back-link" href="#/papers">Back to your papers</a></p></div>
            </section>
        );
    }
    if (load.kind === "error") {
        return <section className="workspace"><p className="error-message">{load.message}</p><p><a className="back-link" href="#/papers">Back to your papers</a></p></section>;
    }

    const { paper } = load;
    const report = paper.report;
    return (
        <section className="workspace">
            <p><a className="back-link" href="#/papers">← All papers</a></p>
            <div className="intro">
                <p className="eyebrow">Research paper</p>
                <h1>{paper.title ?? paper.filename}</h1>
                <p className="intro-copy">
                    {report && report.authors.length > 0 ? `${report.authors.join(", ")} · ` : ""}
                    {paper.page_count ? `${paper.page_count} pages · ` : ""}{formatSize(paper.size_bytes)}
                </p>
                <p><span className={`status-chip status-${paper.status}`}>{STATUS_LABELS[paper.status] ?? paper.status}</span>
                    {paper.detail && <small className={`paper-detail ${paper.status === "failed" ? "failed" : ""}`}> {paper.detail}</small>}
                    {paper.can_retry && <button className="link-button" disabled={retrying} onClick={() => void retry()}> Retry</button>}</p>
                {retryError && <p className="error-message">{retryError}</p>}
            </div>
            <section className="report-section">
                <p className="eyebrow">What we could read</p>
                <h2>Reading report</h2>
                {report ? (
                    <>
                        <ul className="report-stats">
                            <li><strong>{report.page_count ?? "?"}</strong> pages</li>
                            <li><strong>{report.chunk_count}</strong> text passages</li>
                            <li><strong>{report.figure_count}</strong> figures</li>
                        </ul>
                        {report.warnings.length > 0
                            ? <ul className="report-warnings">{report.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
                            : <p className="empty-library">The parser reported no problems.</p>}
                    </>
                ) : (
                    <p className="empty-library">The report appears once the paper has been read.</p>
                )}
            </section>
            <section className="library-section">
                <div className="library-heading"><div><p className="eyebrow">From this paper</p><h2>Videos</h2></div></div>
                <p className="empty-library">No videos yet. Making videos from a paper is the next step of this feature.</p>
            </section>
        </section>
    );
}

export default PaperDetailPage;
