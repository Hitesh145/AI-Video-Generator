import { useEffect, useState } from "react";

export type Route = { page: "studio" } | { page: "papers" } | { page: "paper"; paperId: string };

/** "#/papers/abc" -> the paper page for "abc"; anything unrecognised is the studio. */
export function parseHash(hash: string): Route {
    const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
    if (parts[0] === "papers" && parts.length === 1) return { page: "papers" };
    if (parts[0] === "papers" && parts.length === 2) {
        try {
            return { page: "paper", paperId: decodeURIComponent(parts[1]) };
        } catch {
            return { page: "papers" };
        }
    }
    return { page: "studio" };
}

export function useHashRoute(): Route {
    const [hash, setHash] = useState(window.location.hash);
    useEffect(() => {
        const onChange = () => setHash(window.location.hash);
        window.addEventListener("hashchange", onChange);
        return () => window.removeEventListener("hashchange", onChange);
    }, []);
    return parseHash(hash);
}
