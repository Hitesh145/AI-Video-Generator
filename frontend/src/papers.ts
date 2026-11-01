export type Paper = {
    paper_id: string;
    filename: string;
    size_bytes: number;
    status: string;
    detail: string | null;
    title: string | null;
    page_count: number | null;
    can_retry: boolean;
    created_at: string;
    updated_at: string;
};

export type PaperReport = {
    title: string | null;
    authors: string[];
    page_count: number | null;
    chunk_count: number;
    figure_count: number;
    warnings: string[];
};

export type PaperDetail = Paper & { report: PaperReport | null };

export const MAX_UPLOAD_MB = 50;
export const POLL_INTERVAL_MS = 2000;
export const MAX_POLL_FAILURES = 5;

export const STATUS_LABELS: Record<string, string> = {
    queued: "Waiting",
    parsing: "Reading the PDF",
    chunking: "Splitting into passages",
    storing: "Saving",
    embedding: "Indexing",
    ready: "Ready",
    failed: "Failed",
};

const IN_PROGRESS = new Set(["queued", "parsing", "chunking", "storing", "embedding"]);

export function isInProgress(status: string): boolean {
    return IN_PROGRESS.has(status);
}

export function formatSize(bytes: number): string {
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** The server's plain-language reason from a failed response, or a fallback. */
export async function errorDetail(response: Response, fallback: string): Promise<string> {
    try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === "string") return body.detail;
    } catch {
        // Not JSON: use the fallback.
    }
    return fallback;
}
