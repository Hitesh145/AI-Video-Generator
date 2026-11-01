import type { ReactNode } from "react";
import type { AuthUser } from "./api";

export type ActivePage = "studio" | "papers";

type Props = { user: AuthUser; onLogout: () => Promise<void>; active: ActivePage; children: ReactNode };

function Layout({ user, onLogout, active, children }: Props) {
    return (
        <main className="app-shell">
            <header className="topbar">
                <div className="brand-mark"><span>EDU</span><strong>GEN</strong></div>
                <nav className="nav" aria-label="Main">
                    <a href="#/" className={`nav-link ${active === "studio" ? "active" : ""}`} aria-current={active === "studio" ? "page" : undefined}>Studio</a>
                    <a href="#/papers" className={`nav-link ${active === "papers" ? "active" : ""}`} aria-current={active === "papers" ? "page" : undefined}>Paper videos</a>
                </nav>
                <div className="topbar-right">
                    <div className="topbar-status"><span className="status-dot" /> Video studio <span className="slash">/</span> beta</div>
                    <div className="account"><span className="account-email">{user.email}</span><button className="logout-button" onClick={() => void onLogout()}>Log out</button></div>
                </div>
            </header>
            {children}
            <footer className="footer"><span>EDUGEN AI</span><span>Plan · animate · explain</span></footer>
        </main>
    );
}

export default Layout;
