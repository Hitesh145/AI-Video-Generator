import { useEffect, useState, type ReactNode } from "react";
import { apiFetch, UNAUTHORIZED_EVENT, type AuthUser } from "./api";
import LoginPage from "./LoginPage";

type Props = { children: (user: AuthUser, logout: () => Promise<void>) => ReactNode };

/** Shows the login screen until the server confirms a session, then the app. */
function AuthGate({ children }: Props) {
    const [user, setUser] = useState<AuthUser | null>(null);
    const [checking, setChecking] = useState(true);

    useEffect(() => {
        let cancelled = false;
        apiFetch("/auth/me")
            .then(async (response) => {
                if (!cancelled && response.ok) setUser((await response.json()) as AuthUser);
            })
            .catch(() => {
                // Server unreachable: fall back to the login screen, which reports connection errors.
            })
            .finally(() => {
                if (!cancelled) setChecking(false);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        const onUnauthorized = () => setUser(null);
        window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
        return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    }, []);

    async function logout() {
        try {
            await apiFetch("/auth/logout", { method: "POST" });
        } finally {
            setUser(null);
        }
    }

    if (checking) return <main className="app-shell"><p className="auth-loading">Loading...</p></main>;
    if (!user) return <LoginPage onAuthenticated={setUser} />;
    return <>{children(user, logout)}</>;
}

export default AuthGate;
