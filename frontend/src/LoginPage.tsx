import { useState, type FormEvent } from "react";
import { apiFetch, type AuthUser } from "./api";

type Mode = "login" | "signup";

async function errorText(response: Response): Promise<string> {
    try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === "string") return body.detail;
    } catch {
        // Fall through to the generic message.
    }
    return "Something went wrong. Check your email and password and try again.";
}

function LoginPage({ onAuthenticated }: { onAuthenticated: (user: AuthUser) => void }) {
    const [mode, setMode] = useState<Mode>("login");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);

    async function submit(event: FormEvent) {
        event.preventDefault();
        if (busy) return;
        setBusy(true);
        setError("");
        try {
            const response = await apiFetch(mode === "login" ? "/auth/login" : "/auth/signup", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password }),
            });
            if (!response.ok) {
                setError(await errorText(response));
                return;
            }
            onAuthenticated((await response.json()) as AuthUser);
        } catch {
            setError("Could not reach the server. Is the backend running?");
        } finally {
            setBusy(false);
        }
    }

    return (
        <main className="app-shell">
            <header className="topbar"><div className="brand-mark"><span>EDU</span><strong>GEN</strong></div></header>
            <section className="workspace">
                <form className="login-card" onSubmit={submit}>
                    <p className="panel-kicker">{mode === "login" ? "Welcome back" : "New here"}</p>
                    <h2>{mode === "login" ? "Sign in to the studio" : "Create your account"}</h2>
                    <label>Email<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
                    <label>Password<input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
                    {mode === "signup" && <p className="hint">At least 8 characters.</p>}
                    {error && <p className="error-message">{error}</p>}
                    <button className="generate-button" type="submit" disabled={busy || !email || !password}>{busy ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}</button>
                    <button className="link-button" type="button" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); }}>
                        {mode === "login" ? "No account yet? Create one" : "Already have an account? Sign in"}
                    </button>
                </form>
            </section>
        </main>
    );
}

export default LoginPage;
