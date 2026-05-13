import { useMemo, useState } from 'react'

export default function RetrievalTab({
  viewMode = 'combined',
  text,
  retrievalToast,
  showImportantInformation,
  toggleImportantInformation,
  selectedMaterial,
  materialInsight,
  materialInsightLoading,
  summaryFormatFlags,
  insightSummarySections,
  retrievalOverview,
  searchableCount,
  materialCount,
  blockedCount,
  coverageMaterials,
  selectedCoverageSource,
  selectedCoverageMaterial,
  handleCoverageSourceChange,
  inspectMaterial,
  Badge,
  retrievalResults,
  showKnowledgeSearch,
  toggleKnowledgeSearch,
  retrievalSearch,
  setRetrievalSearch,
  runRetrievalSearch,
  retrievalLoading,
  findMatchingWikiTarget,
  wikiIndex,
  openWikiSourceFromRetrieval,
  submitRetrievalFeedback,
  feedbackSubmitting,
  feedbackRecorded,
  fileAnswerToWiki,
  answerFiled,
  feedbackSummaryLoading,
  feedbackSummary,
  setLightboxImage,
  setPdfViewerUrl,
  isResultRelevant,
  extractQueryKeywords,
  selectedSuggestedQa,
  onSuggestedQuestionSelect,
  isAdmin,
  uiAlignedQaItems,
}) {
  const [activeInsightPanel, setActiveInsightPanel] = useState('summary')
  const showInsightsPanel = viewMode !== 'search'
  const showSearchPanel = viewMode !== 'insights'
  const isWikiBasedAnswer =
    retrievalResults?.answer_model === 'wiki-based'
    || String(retrievalResults?.answer_path || '').toLowerCase().startsWith('wiki')

  const normalizeQuestion = (value) =>
    String(value || '')
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()

  const suggestedQuestions = useMemo(() => {
    const fromInsight = Array.isArray(materialInsight?.suggested_questions)
      ? materialInsight.suggested_questions
      : []

    const merged = [...fromInsight]
    const deduped = []
    for (const question of merged) {
      const clean = String(question || '').trim()
      if (!clean) {
        continue
      }
      const normalized = normalizeQuestion(clean)
      if (!normalized) {
        continue
      }
      if (deduped.every((existing) => normalizeQuestion(existing) !== normalized)) {
        deduped.push(clean)
      }
    }
    return deduped
  }, [materialInsight])

  const answerSlides = useMemo(() => {
    const selectedQuestion = String(selectedSuggestedQa?.question || '').trim()
    if (!selectedQuestion) {
      return []
    }

    const selectedQuestionNorm = normalizeQuestion(selectedQuestion)
    const selectedTokens = new Set(selectedQuestionNorm.split(' ').filter((token) => token.length >= 4))

    const slides = []

    const liveQueryNorm = normalizeQuestion(retrievalResults?.retrieval_query || retrievalSearch?.query)
    const liveAnswer = String(retrievalResults?.answer || '').trim()
    if (
      liveAnswer
      && liveQueryNorm
      && (liveQueryNorm === selectedQuestionNorm
        || liveQueryNorm.includes(selectedQuestionNorm)
        || selectedQuestionNorm.includes(liveQueryNorm))
    ) {
      slides.push({
        id: `live-${selectedQuestionNorm}`,
        title: text.retrieval.liveSearchAnswerTitle ?? 'Live knowledge-search answer',
        question: retrievalResults?.retrieval_query || retrievalSearch?.query || selectedQuestion,
        answer: liveAnswer,
      })
    }

    const related = Array.isArray(uiAlignedQaItems) ? uiAlignedQaItems : []
    const relatedSlides = related
      .map((item) => {
        const question = String(item?.question || '').trim()
        const answer = String(item?.answer || '').trim()
        if (!question || !answer) {
          return null
        }
        const normalized = normalizeQuestion(question)
        if (!normalized || normalized === selectedQuestionNorm) {
          return null
        }

        const tokens = new Set(normalized.split(' ').filter((token) => token.length >= 4))
        const overlap = [...tokens].filter((token) => selectedTokens.has(token)).length
        const score = selectedTokens.size > 0 ? overlap / selectedTokens.size : 0
        if (score < 0.35 && !normalized.includes(selectedQuestionNorm) && !selectedQuestionNorm.includes(normalized)) {
          return null
        }

        return {
          id: `related-${normalized}`,
          title: text.retrieval.relatedAnswerTitle ?? 'Related aligned answer',
          question,
          answer,
          score,
        }
      })
      .filter(Boolean)
      .sort((a, b) => b.score - a.score)
      .slice(0, 4)

    return [...slides, ...relatedSlides]
  }, [selectedSuggestedQa, retrievalResults, retrievalSearch, text, uiAlignedQaItems])

  const liveAnswerSlide = answerSlides.find((item) => item.id.startsWith('live-'))
  const relatedAnswerSlides = answerSlides.filter(
    (item) => !item.id.startsWith('selected-') && !item.id.startsWith('live-'),
  )

  return (
    <>
      {retrievalToast && (
        <div className="retrieval-toast" role="status" aria-live="polite">
          {retrievalToast}
        </div>
      )}
      {showInsightsPanel && (
      <section className={`panel panel-wide panel-ai-review ${showImportantInformation && materialInsight && !materialInsightLoading ? 'panel-ai-review-expanded' : ''}`}>
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.retrieval.aiReview}</p>
            <h3>{text.retrieval.importantInformation}</h3>
          </div>
          <div className="panel-header-actions">
            <span className="ai-review-selected-material">{selectedMaterial || text.retrieval.chooseMaterial}</span>
            <button
              type="button"
              className="ghost-inline-button panel-toggle-button"
              onClick={toggleImportantInformation}
              aria-expanded={showImportantInformation}
            >
              {showImportantInformation ? text.retrieval.hide : text.retrieval.show}
            </button>
          </div>
        </div>
        {showImportantInformation && (
          <>
            <div className="coverage-hybrid">
              {coverageMaterials.length > 0 ? (
                <div className="coverage-inline-row">
                  <select
                    id="coverage-material-select"
                    title={selectedCoverageMaterial?.source || ''}
                    value={selectedCoverageSource || ''}
                    onChange={(event) => handleCoverageSourceChange(event.target.value)}
                  >
                    <option value="">{text.retrieval.chooseMaterial ?? 'Select a document'}</option>
                    {coverageMaterials.map((item) => (
                      <option key={item.source} value={item.source} title={item.source}>
                        {item.source}
                      </option>
                    ))}
                  </select>
                  {selectedCoverageMaterial && (
                    <>
                      <Badge value={selectedCoverageMaterial.status} />
                      <button className="ghost-inline-button" onClick={() => inspectMaterial(selectedCoverageMaterial.source)}>
                        {text.retrieval.inspectWithAI}
                      </button>
                    </>
                  )}
                </div>
              ) : (
                <p className="empty-state">{text.retrieval.coverageEmpty}</p>
              )}
            </div>

            {!materialInsight && !materialInsightLoading && (
              <p className="empty-state">{text.retrieval.inspectHint}</p>
            )}
            {materialInsightLoading && (
              <p className="empty-state">{text.retrieval.generatingInsight}</p>
            )}
            {materialInsight && !materialInsightLoading && (
              <div className="insight-grid">
                <div className="insight-panel-toggle">
                  <button
                    type="button"
                    className={`insight-panel-tab${activeInsightPanel === 'summary' ? ' active' : ''}`}
                    onClick={() => setActiveInsightPanel('summary')}
                  >
                    {text.retrieval.summary ?? 'Summary'}
                  </button>
                  <button
                    type="button"
                    className={`insight-panel-tab${activeInsightPanel === 'questions' ? ' active' : ''}`}
                    onClick={() => setActiveInsightPanel('questions')}
                  >
                    {text.retrieval.suggestedQuestions ?? 'Suggested Questions'}
                  </button>
                </div>
                {activeInsightPanel === 'summary' && (
                <article className="insight-card insight-card-wide insight-summary-card">
                  <span className="insight-label">{text.retrieval.summary}</span>
                  {(summaryFormatFlags.hasLegacyHeadings || summaryFormatFlags.isPartialStructured) && (
                    <p className="insight-summary-hint">
                      {text.retrieval.summaryHint}
                    </p>
                  )}
                  {insightSummarySections.length > 0 ? (
                    <div className="insight-summary-sections">
                      {insightSummarySections.map((section) => (
                        <div key={`${section.heading}-${section.body.slice(0, 32)}`} className="insight-summary-section">
                          <h4>{section.heading}</h4>
                          <p>{section.body}</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p>{materialInsight.summary}</p>
                  )}
                </article>
                )}
                {activeInsightPanel === 'questions' && (
                <article className="insight-card insight-card-wide">
                  <div className="insight-two-column">
                    <div>
                      <span className="insight-label">{text.retrieval.suggestedQuestions}</span>
                      <ul className="insight-list">
                        {suggestedQuestions.map((question) => (
                          <li key={question}>
                            <button
                              type="button"
                              className="ghost-inline-button"
                              onClick={() => onSuggestedQuestionSelect?.(question)}
                            >
                              {question}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>

                    <div>
                      <span className="insight-label">{text.retrieval.answerSlider ?? 'Answer slider'}</span>
                      {selectedSuggestedQa?.question ? (
                        <div className="qa-collapsible-stack">
                          <details className="qa-collapsible" open>
                            <summary>{liveAnswerSlide?.title ?? (text.retrieval.liveSearchAnswerTitle ?? 'Live knowledge-search answer')}</summary>
                            <div className="qa-collapsible-body">
                              <strong>{liveAnswerSlide?.question || retrievalSearch?.query || selectedSuggestedQa?.question}</strong>
                              <p>
                                {liveAnswerSlide?.answer
                                  || (text.retrieval.runMatchingSearch
                                    ?? 'Run a matching Knowledge search for this question to view a live answer here.')}
                              </p>
                            </div>
                          </details>

                          {relatedAnswerSlides.length > 0 && (
                            <div className="qa-related-stack">
                              {relatedAnswerSlides.map((item) => (
                                <article key={item.id} className="qa-slide-card">
                                  <span className="insight-label">{item.title}</span>
                                  <strong>{item.question}</strong>
                                  <p>{item.answer}</p>
                                </article>
                              ))}
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="empty-state">{text.retrieval.noAlignedAnswer ?? 'Select a suggested question to view answers.'}</p>
                      )}
                    </div>
                  </div>
                </article>
                )}
              </div>
            )}
          </>
        )}
      </section>
      )}

      {showSearchPanel && (
      <section className="panel panel-wide">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.retrieval.retrievalView}</p>
            <h3>{text.retrieval.knowledgeSearch}</h3>
          </div>
          <div className="panel-header-actions">
            <span>{retrievalResults?.result_count ?? 0} {text.retrieval.resultsSuffix}</span>
            <button
              type="button"
              className="ghost-inline-button panel-toggle-button"
              onClick={toggleKnowledgeSearch}
              aria-expanded={showKnowledgeSearch}
            >
              {showKnowledgeSearch ? text.retrieval.hide : text.retrieval.show}
            </button>
          </div>
        </div>
        {showKnowledgeSearch && (
          <>
            <div className="search-form">
              <input
                type="text"
                placeholder={text.retrieval.queryPlaceholder}
                value={retrievalSearch.query}
                onChange={(event) =>
                  setRetrievalSearch((current) => ({ ...current, query: event.target.value }))
                }
              />
              <button className="primary-button" onClick={runRetrievalSearch} disabled={retrievalLoading}>
                {retrievalLoading ? text.retrieval.searching : text.retrieval.searchMaterial}
              </button>
            </div>
            {retrievalResults && (
              <div className="search-summary">
                <strong>{text.retrieval.retrievalQuery}</strong>
                <p>{retrievalResults.retrieval_query}</p>
              </div>
            )}
            {retrievalResults?.answer && (
              <div className="search-answer">
                <strong>{text.retrieval.smartAnswer}</strong>
                <p>{retrievalResults.answer}</p>
                {(retrievalResults.citations || []).length > 0 && (
                  <div className="citation-block">
                    <strong>{text.retrieval.citations}</strong>
                    <ul className="citation-list">
                      {(retrievalResults.citations || []).map((item, index) => (
                        <li key={`${item.source}-${item.chunk_id}-${index}`} className="citation-item">
                          {item.source} ({item.chunk_id})
                          {findMatchingWikiTarget(item.source, wikiIndex) && (
                            <button
                              type="button"
                              className="ghost-inline-button citation-wiki-link"
                              onClick={() => openWikiSourceFromRetrieval(item.source)}
                            >
                              {text.wiki.openFromCitation ?? 'Open wiki page'}
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="search-answer-meta">
                  <span>{text.retrieval.model}: {retrievalResults.answer_model || '-'}</span>
                  <span>{text.retrieval.orchestrator}: {retrievalResults.orchestrator || '-'}</span>
                  <span>{text.retrieval.engine}: {retrievalResults.answer_path || '-'}</span>
                  <span>{text.retrieval.confidence}: {Math.round((Number(retrievalResults.answer_confidence || 0)) * 100)}%</span>
                  <span>{text.retrieval.confidenceSource}: {retrievalResults.answer_confidence_source || '-'}</span>
                  <span>{text.retrieval.fallback}: {retrievalResults.fallback_used ? (retrievalResults.fallback_reason || text.retrieval.fallbackYes) : text.retrieval.fallbackNo}</span>
                </div>

                {retrievalResults.llm_answer && retrievalResults.llm_answer !== retrievalResults.answer && (
                  <div className="search-summary" style={{ marginTop: '0.75rem' }}>
                    <strong>{text.retrieval.llmCandidate}</strong>
                    <p>{retrievalResults.llm_answer}</p>
                    <div className="search-answer-meta">
                      <span>{text.retrieval.model}: {retrievalResults.llm_answer_model || '-'}</span>
                      <span>{text.retrieval.engine}: llm</span>
                      <span>{text.retrieval.confidence}: {Math.round((Number(retrievalResults.llm_answer_confidence || 0)) * 100)}%</span>
                      <span>{text.retrieval.confidenceSource}: {retrievalResults.llm_answer_confidence_source || '-'}</span>
                    </div>
                  </div>
                )}

                {retrievalResults.retrieval_answer && retrievalResults.retrieval_answer !== retrievalResults.answer && (
                  <div className="search-summary" style={{ marginTop: '0.75rem' }}>
                    <strong>{text.retrieval.retrievalCandidate}</strong>
                    <p>{retrievalResults.retrieval_answer}</p>
                    <div className="search-answer-meta">
                      <span>{text.retrieval.model}: {retrievalResults.retrieval_answer_model || text.retrieval.retrievalRuleEngine}</span>
                      <span>{text.retrieval.engine}: {text.retrieval.retrievalRuleEngine}</span>
                      <span>{text.retrieval.confidence}: {Math.round((Number(retrievalResults.retrieval_answer_confidence || 0)) * 100)}%</span>
                      <span>{text.retrieval.confidenceSource}: {retrievalResults.retrieval_answer_confidence_source || text.retrieval.retrievalRuleEngine}</span>
                    </div>
                  </div>
                )}

                <div className="search-answer-meta" style={{ marginTop: '0.5rem' }}>
                  <span>{text.retrieval.helpfulPrompt}</span>
                  <button
                    type="button"
                    className="ghost-inline-button"
                    onClick={() => submitRetrievalFeedback(true)}
                    disabled={feedbackSubmitting || feedbackRecorded === true}
                  >
                    {feedbackRecorded === true ? text.retrieval.helpfulRecorded : text.retrieval.helpful}
                  </button>
                  <button
                    type="button"
                    className="ghost-inline-button"
                    onClick={() => submitRetrievalFeedback(false)}
                    disabled={feedbackSubmitting || feedbackRecorded === false}
                  >
                    {feedbackRecorded === false ? text.retrieval.notHelpfulRecorded : text.retrieval.notHelpful}
                  </button>
                  <button
                    type="button"
                    className="ghost-inline-button"
                    onClick={fileAnswerToWiki}
                    disabled={answerFiled || !retrievalResults?.answer || isWikiBasedAnswer}
                    title={isWikiBasedAnswer ? 'This answer is already wiki-based.' : undefined}
                  >
                    {isWikiBasedAnswer
                      ? (text.retrieval.alreadyWikiBased ?? 'Already in Wiki')
                      : answerFiled
                        ? text.retrieval.answerFiled
                        : text.retrieval.fileAsWiki}
                  </button>
                </div>

                {isAdmin && (
                    <div className="feedback-summary-card">
                      <strong>{text.retrieval.feedbackSummary}</strong>
                      {feedbackSummaryLoading && <p>{text.retrieval.loadingSummary}</p>}
                      {!feedbackSummaryLoading && feedbackSummary && (
                        <>
                          <div className="feedback-summary-metrics">
                            <span>{text.retrieval.total}: {feedbackSummary.total ?? 0}</span>
                            <span>{text.retrieval.helpfulLabel}: {feedbackSummary.helpful ?? 0}</span>
                            <span>{text.retrieval.notHelpfulLabel}: {feedbackSummary.not_helpful ?? 0}</span>
                            <span>
                              {text.retrieval.helpfulRatio}: {Math.round(Number(feedbackSummary.helpful_ratio || 0) * 100)}%
                            </span>
                          </div>
                          {(feedbackSummary.latest || []).length > 0 && (
                            <div className="feedback-summary-latest">
                              {text.retrieval.latest}: {(feedbackSummary.latest || [])
                                .slice(-3)
                                .map((item) => (item.helpful ? 'helpful' : 'not helpful'))
                                .join(text.retrieval.latestJoiner)}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                )}
              </div>
            )}
            {(() => {
              const relevantImages = (retrievalResults?.results || [])
                .filter((r) => r.page_image_url)
                .filter((r) => isResultRelevant(r, extractQueryKeywords(retrievalResults.retrieval_query)))
                .filter((r, idx, arr) => arr.findIndex((x) => x.page_image_url === r.page_image_url) === idx)
                .slice(0, 4)
              return relevantImages.length > 0 ? (
                <div className="chunk-page-images">
                  <div className="chunk-page-images-header">
                    <strong>{text.retrieval.referencedPages}</strong>
                    <span className="chunk-page-images-hint">{text.retrieval.referencedPagesHint}</span>
                  </div>
                  <div className="chunk-page-images-grid">
                    {relevantImages.map((result) => (
                      <div
                        key={result.chunk_id}
                        className="chunk-page-image-card"
                        onClick={() => setLightboxImage({ url: result.page_image_url, source: result.source, excerpt: result.excerpt })}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => e.key === 'Enter' && setLightboxImage({ url: result.page_image_url, source: result.source, excerpt: result.excerpt })}
                        aria-label={`Expand page from ${result.source}`}
                      >
                        <img
                          src={result.page_image_url}
                          alt={`Page from ${result.source}`}
                          loading="lazy"
                          className="chunk-page-image-img"
                        />
                        <div className="chunk-page-image-meta">
                          <span className="chunk-page-image-source">{result.source}</span>
                          <p className="chunk-page-image-excerpt">{(result.excerpt || '').slice(0, 90)}…</p>
                          {result.source.endsWith('.pdf') && (
                            <button
                              className="view-pdf-btn"
                              onClick={(e) => {
                                e.stopPropagation()
                                setPdfViewerUrl(`/api/admin/visual-reference-document?source=${encodeURIComponent(result.source)}`)
                              }}
                              title={text.retrieval.viewPdfTitle}
                            >
                              {text.retrieval.viewPdf}
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null
            })()}
            {!retrievalResults && (
              <p className="empty-state">{text.retrieval.empty}</p>
            )}
          </>
        )}
      </section>
      )}
    </>
  )
}
