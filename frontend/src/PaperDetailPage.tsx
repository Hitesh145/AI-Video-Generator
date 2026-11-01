function PaperDetailPage({ paperId }: { paperId: string }) {
    return (
        <section className="workspace">
            <div className="intro"><p className="eyebrow">Paper</p><h1>{paperId}</h1><p><a href="#/papers">Back to your papers</a></p></div>
        </section>
    );
}

export default PaperDetailPage;
