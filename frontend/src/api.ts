export const API_BASE = "http://localhost:8000";
export const UNAUTHORIZED_EVENT = "edugen:unauthorized";

export type AuthUser = { user_id: string; email: string };

// 401s from these are expected (wrong password, not logged in yet) and handled by the caller.
const AUTH_PATHS = ["/auth/login", "/auth/signup", "/auth/me"];

/** fetch against the backend, always sending the session cookie. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
    const response = await fetch(`${API_BASE}${path}`, { ...init, credentials: "include" });
    if (response.status === 401 && !AUTH_PATHS.includes(path)) {
        window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    return response;
}
