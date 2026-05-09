export default function WikiTab({
  text,
  wikiLoading,
  wikiIndex,
  wikiImpact,
  wikiImpactFilter,
  setWikiImpactFilter,
  showImpactBucket,
  openImpactPage,
  wikiPage,
  setWikiPage,
  wikiSearchTerm,
  setWikiSearchTerm,
  filteredWikiPageCount,
  totalWikiPageCount,
  filteredWikiSources,
  filteredWikiEntities,
  filteredWikiAnswers,
  filteredWikiConcepts,
  fetchWikiIndex,
  fetchWikiPage,
  wikiReviewSubmitting,
  updateWikiReviewState,
  canManageReview,
}) {
  return (
    <>
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.wiki.browseTitle}</p>
            <h3>{text.wiki.sourcesHeading}</h3>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            {wikiPage && (
              <button className="btn btn-secondary" onClick={() => setWikiPage(null)}>
                {text.wiki.backToIndex}
              </button>
            )}
            <button className="btn btn-secondary" onClick={fetchWikiIndex} disabled={wikiLoading}>
              {wikiLoading ? text.wiki.loading : text.wiki.refresh}
            </button>
          </div>
        </div>

        {canManageReview && wikiImpact && (
          <details style={{ marginTop: '8px' }}>
            <summary style={{ cursor: 'pointer', color: '#3f4a5a', fontSize: '13px', fontWeight: 600 }}>
              {text.wiki.impactDetails ?? 'Impact Details'}
            </summary>
            <div style={{ marginTop: '10px' }}>
              <p style={{ margin: '0 0 8px 0', fontSize: '12px', color: '#667085' }}>
                {(text.wiki.impactSummaryPrefix ?? 'Changed')}: {wikiImpact?.counts?.changed_sources ?? 0} • {(text.wiki.impactDeletedPrefix ?? 'Deleted')}: {wikiImpact?.counts?.deleted_sources ?? 0}
              </p>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '12px' }}>
                {['all', 'source', 'entity', 'concept', 'deleted'].map((filterKey) => (
                  <button
                    key={filterKey}
                    type="button"
                    className="ghost-inline-button"
                    onClick={() => setWikiImpactFilter(filterKey)}
                    disabled={wikiImpactFilter === filterKey}
                  >
                    {text.wiki[`filter${filterKey.charAt(0).toUpperCase()}${filterKey.slice(1)}`] ?? filterKey}
                  </button>
                ))}
              </div>

              {showImpactBucket('source') && (
                <div style={{ marginBottom: '10px' }}>
                  <strong style={{ fontSize: '12px', color: '#475467' }}>{text.wiki.affectedSourcePages ?? 'Affected Source Pages'}</strong>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '6px' }}>
                    {(wikiImpact?.affected?.source_pages || []).slice(0, 24).map((path) => (
                      <button key={path} className="ghost-inline-button" onClick={() => openImpactPage(path)}>
                        {path}
                      </button>
                    ))}
                    {(!wikiImpact?.affected?.source_pages || wikiImpact.affected.source_pages.length === 0) && (
                      <span style={{ fontSize: '12px', color: '#98a2b3' }}>{text.wiki.none ?? 'None'}</span>
                    )}
                  </div>
                </div>
              )}

              {showImpactBucket('entity') && (
                <div style={{ marginBottom: '10px' }}>
                  <strong style={{ fontSize: '12px', color: '#475467' }}>{text.wiki.affectedEntityPages ?? 'Affected Entity Pages'}</strong>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '6px' }}>
                    {(wikiImpact?.affected?.entity_pages || []).slice(0, 24).map((path) => (
                      <button key={path} className="ghost-inline-button" onClick={() => openImpactPage(path)}>
                        {path}
                      </button>
                    ))}
                    {(!wikiImpact?.affected?.entity_pages || wikiImpact.affected.entity_pages.length === 0) && (
                      <span style={{ fontSize: '12px', color: '#98a2b3' }}>{text.wiki.none ?? 'None'}</span>
                    )}
                  </div>
                </div>
              )}

              {showImpactBucket('concept') && (
                <div style={{ marginBottom: '10px' }}>
                  <strong style={{ fontSize: '12px', color: '#475467' }}>{text.wiki.affectedConceptPages ?? 'Affected Concept Pages'}</strong>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '6px' }}>
                    {(wikiImpact?.affected?.concept_pages || []).slice(0, 24).map((path) => (
                      <button key={path} className="ghost-inline-button" onClick={() => openImpactPage(path)}>
                        {path}
                      </button>
                    ))}
                    {(!wikiImpact?.affected?.concept_pages || wikiImpact.affected.concept_pages.length === 0) && (
                      <span style={{ fontSize: '12px', color: '#98a2b3' }}>{text.wiki.none ?? 'None'}</span>
                    )}
                  </div>
                </div>
              )}

              {showImpactBucket('deleted') && (
                <div>
                  <strong style={{ fontSize: '12px', color: '#475467' }}>{text.wiki.deletedSourcePages ?? 'Deleted Source Pages'}</strong>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '6px' }}>
                    {(wikiImpact?.affected?.deleted_source_pages || []).slice(0, 24).map((path) => (
                      <span
                        key={path}
                        style={{
                          display: 'inline-block',
                          padding: '4px 12px',
                          borderRadius: '999px',
                          border: '1px solid #fecaca',
                          background: '#fef2f2',
                          color: '#b42318',
                          fontSize: '13px',
                        }}
                      >
                        {path}
                      </span>
                    ))}
                    {(!wikiImpact?.affected?.deleted_source_pages || wikiImpact.affected.deleted_source_pages.length === 0) && (
                      <span style={{ fontSize: '12px', color: '#98a2b3' }}>{text.wiki.none ?? 'None'}</span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </details>
        )}

        {!wikiIndex && !wikiLoading && (
          <p style={{ color: '#999', fontSize: '14px' }}>{text.wiki.empty}</p>
        )}

        {wikiIndex && (
          <>
            {!wikiPage && (
              <>
                <div className="wiki-search-bar">
                  <input
                    type="text"
                    placeholder={text.wiki.searchPlaceholder ?? 'Search wiki pages'}
                    value={wikiSearchTerm}
                    onChange={(event) => setWikiSearchTerm(event.target.value)}
                    aria-label={text.wiki.searchAriaLabel ?? 'Search wiki pages'}
                  />
                  {wikiSearchTerm && (
                    <button type="button" className="ghost-inline-button" onClick={() => setWikiSearchTerm('')}>
                      {text.wiki.clearSearch ?? 'Clear'}
                    </button>
                  )}
                  <span className="wiki-search-meta">
                    {filteredWikiPageCount}/{totalWikiPageCount} {text.wiki.matchesLabel ?? 'matches'}
                  </span>
                </div>

                {filteredWikiSources.length > 0 && (
                  <>
                    <h4 style={{ marginBottom: '8px', fontSize: '13px', color: '#5b6470' }}>{text.wiki.documents}</h4>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '16px' }}>
                      {filteredWikiSources.map((slug) => (
                        <button
                          key={slug}
                          onClick={() => fetchWikiPage('source', slug)}
                          style={{
                            padding: '4px 12px',
                            borderRadius: '999px',
                            border: '1px solid #dbe3ec',
                            background: '#f4f7fb',
                            cursor: 'pointer',
                            fontSize: '13px',
                          }}
                        >
                          {slug.replace(/-/g, ' ')}
                        </button>
                      ))}
                    </div>
                  </>
                )}

                {filteredWikiEntities.length > 0 && (
                  <>
                    <h4 style={{ marginBottom: '8px', fontSize: '13px', color: '#5b6470' }}>{text.wiki.entities}</h4>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                      {filteredWikiEntities.map((slug) => (
                        <button
                          key={slug}
                          onClick={() => fetchWikiPage('entity', slug)}
                          style={{
                            padding: '4px 12px',
                            borderRadius: '999px',
                            border: '1px solid #c7d2fe',
                            background: '#eef2ff',
                            cursor: 'pointer',
                            fontSize: '13px',
                          }}
                        >
                          {slug.replace(/-/g, ' ')}
                        </button>
                      ))}
                    </div>
                  </>
                )}

                {filteredWikiAnswers.length > 0 && (
                  <>
                    <h4 style={{ marginBottom: '8px', marginTop: '16px', fontSize: '13px', color: '#5b6470' }}>{text.wiki.answersHeading}</h4>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                      {filteredWikiAnswers.map((slug) => (
                        <button
                          key={slug}
                          onClick={() => fetchWikiPage('answer', slug)}
                          style={{
                            padding: '4px 12px',
                            borderRadius: '999px',
                            border: '1px solid #bbf7d0',
                            background: '#f0fdf4',
                            cursor: 'pointer',
                            fontSize: '13px',
                          }}
                        >
                          {slug.replace(/-/g, ' ')}
                        </button>
                      ))}
                    </div>
                  </>
                )}

                {filteredWikiConcepts.length > 0 && (
                  <>
                    <h4 style={{ marginBottom: '8px', marginTop: '16px', fontSize: '13px', color: '#5b6470' }}>{text.wiki.concepts ?? 'Concepts'}</h4>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                      {filteredWikiConcepts.map((slug) => (
                        <button
                          key={slug}
                          onClick={() => fetchWikiPage('concept', slug)}
                          style={{
                            padding: '4px 12px',
                            borderRadius: '999px',
                            border: '1px solid #fde68a',
                            background: '#fffbeb',
                            cursor: 'pointer',
                            fontSize: '13px',
                          }}
                        >
                          {slug.replace(/-/g, ' ')}
                        </button>
                      ))}
                    </div>
                  </>
                )}

                {totalWikiPageCount === 0 && (
                  <p style={{ color: '#999', fontSize: '14px' }}>{text.wiki.noPagesYet}</p>
                )}
                {totalWikiPageCount > 0 && filteredWikiPageCount === 0 && (
                  <p style={{ color: '#999', fontSize: '14px' }}>
                    {text.wiki.noMatches ?? 'No wiki pages match your search.'}
                  </p>
                )}
              </>
            )}

            {wikiPage && (
              <>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '12px',
                    marginBottom: '10px',
                    flexWrap: 'wrap',
                  }}
                >
                  <div style={{ fontSize: '13px', color: '#5b6470' }}>
                    {text.wiki.currentReview ?? 'Review'}: <strong>{wikiPage.review?.status ?? 'draft'}</strong>
                    {wikiPage.review?.updated_at ? ` • ${wikiPage.review.updated_at}` : ''}
                  </div>
                  {canManageReview && (
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      <button
                        className="ghost-inline-button"
                        onClick={() => updateWikiReviewState('draft')}
                        disabled={wikiReviewSubmitting || wikiPage.review?.status === 'draft'}
                      >
                        {text.wiki.setDraft ?? 'Set Draft'}
                      </button>
                      <button
                        className="ghost-inline-button"
                        onClick={() => updateWikiReviewState('reviewed')}
                        disabled={wikiReviewSubmitting || wikiPage.review?.status === 'reviewed'}
                      >
                        {text.wiki.setReviewed ?? 'Set Reviewed'}
                      </button>
                      <button
                        className="ghost-inline-button"
                        onClick={() => updateWikiReviewState('approved')}
                        disabled={wikiReviewSubmitting || wikiPage.review?.status === 'approved'}
                      >
                        {text.wiki.setApproved ?? 'Set Approved'}
                      </button>
                    </div>
                  )}
                </div>
                <div
                  style={{
                    fontFamily: 'monospace',
                    fontSize: '13px',
                    whiteSpace: 'pre-wrap',
                    lineHeight: '1.6',
                    background: '#f9fafb',
                    borderRadius: '8px',
                    padding: '16px',
                    overflowX: 'auto',
                  }}
                >
                  {wikiPage.content}
                </div>
              </>
            )}
          </>
        )}
      </section>
    </>
  )
}
