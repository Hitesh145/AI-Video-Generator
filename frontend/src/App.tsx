import type { AuthUser } from "./api";
import Layout from "./Layout";
import PaperDetailPage from "./PaperDetailPage";
import PapersPage from "./PapersPage";
import StudioPage from "./StudioPage";
import { useHashRoute } from "./useHashRoute";

function App({ user, onLogout }: { user: AuthUser; onLogout: () => Promise<void> }) {
    const route = useHashRoute();

    return (
        <Layout user={user} onLogout={onLogout} active={route.page === "studio" ? "studio" : "papers"}>
            {route.page === "studio" && <StudioPage />}
            {route.page === "papers" && <PapersPage />}
            {route.page === "paper" && <PaperDetailPage paperId={route.paperId} />}
        </Layout>
    );
}

export default App;
