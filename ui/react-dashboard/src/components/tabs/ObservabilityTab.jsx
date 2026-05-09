export default function ObservabilityTab({
  text,
  langsmithStatus,
  evaluationLoading,
  evaluationSummary,
  warmCacheActionLoading,
  runWarmCache,
  clearSemanticCache,
  warmCacheStatus,
  semanticCacheStats,
  warmCacheMessage,
  deployIntelStatus,
  fetchDeployIntelStatus,
  clearingSearchCache,
  clearRetrievalSearchCache,
  searchCacheClearedMsg,
  langsmithTraceLimit,
  setLangsmithTraceLimit,
  langsmithTracesLoading,
  langsmithTraces,
  buildLangsmithTraceUrl,
  formatStageLabel,
  promptUsage,
  promptUsageLoading,
  fetchPromptUsage,
}) {
  return (
    <>
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.tabs.observability}</p>
            <h3>{text.observability.langsmithIntegration}</h3>
          </div>
          {langsmithStatus?.enabled && (
            <span style={{ color: '#12715b', fontWeight: '500' }}>● {text.observability.active}</span>
          )}
        </div>
        <div className="stats-grid">
          <div className="stat-card stat-card-default">
            <span>{text.observability.status}</span>
            <strong>{langsmithStatus?.enabled ? text.observability.enabled : text.observability.disabled}</strong>
            <small>{langsmithStatus?.configured ? text.observability.fullyConfigured : text.observability.notConfigured}</small>
          </div>
          <div className="stat-card stat-card-default">
            <span>{text.observability.apiKey}</span>
            <strong>{langsmithStatus?.api_key_present ? text.observability.present : text.observability.missing}</strong>
            <small>{langsmithStatus?.project || text.observability.noProject}</small>
          </div>
          <div className="stat-card stat-card-default">
            <span>{text.observability.tracing}</span>
            <strong>{langsmithStatus?.tracing ? text.observability.enabled : text.observability.disabled}</strong>
            <small>{langsmithStatus?.endpoint || text.observability.defaultEndpoint}</small>
          </div>
        </div>
      </section>

      {langsmithStatus?.configured && (
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">{text.observability.dashboard}</p>
              <h3>{text.observability.viewProject}</h3>
            </div>
            {langsmithStatus?.project && (
              <a
                href={`https://smith.langchain.com/projects/p?name=${langsmithStatus.project}`}
                target="_blank"
                rel="noopener noreferrer"
                className="primary-button"
                style={{ textDecoration: 'none', display: 'inline-block', padding: '8px 12px' }}
              >
                {text.observability.openLangsmith}
              </a>
            )}
          </div>
          <p style={{ marginBottom: '16px', color: '#666' }}>
            Access LangSmith at{' '}
            <a href="https://smith.langchain.com" target="_blank" rel="noopener noreferrer">
              smith.langchain.com
            </a>{' '}
            to view your trace runs and logs.
          </p>
          <p style={{ color: '#666', fontSize: '14px' }}>
            {text.observability.projectName}: <strong>{langsmithStatus?.project || 'self-learning-console'}</strong>
          </p>
        </section>
      )}

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.observability.evaluation}</p>
            <h3>{text.observability.qualityChecks}</h3>
          </div>
        </div>
        {evaluationLoading && <p className="empty-state">{text.observability.loadingEvaluation}</p>}
        {!evaluationLoading && evaluationSummary && (
          <div className="evaluation-grid">
            <div className="stat-card stat-card-default">
              <span>{text.observability.evalStatus}</span>
              <strong>{evaluationSummary.status || '-'}</strong>
              <small>{evaluationSummary.recommendation || '-'}</small>
            </div>
            <div className="stat-card stat-card-default">
              <span>{text.observability.helpfulRatio}</span>
              <strong>{Math.round(Number(evaluationSummary.helpful_ratio || 0) * 100)}%</strong>
              <small>{text.observability.totalFeedback}: {evaluationSummary.total_feedback ?? 0}</small>
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.observability.semanticWarmCache}</p>
            <h3>{text.observability.semanticWarmCacheTitle}</h3>
          </div>
          <div className="trace-toolbar">
            <button className="secondary-button" disabled={warmCacheActionLoading} onClick={runWarmCache}>
              {warmCacheActionLoading ? text.observability.loading : text.observability.runWarmCache}
            </button>
            <button className="secondary-button" disabled={warmCacheActionLoading} onClick={clearSemanticCache}>
              {text.observability.clearSemanticCache}
            </button>
          </div>
        </div>
        <div className="stats-grid">
          <div className="stat-card stat-card-default">
            <span>{text.observability.warmStatus}</span>
            <strong>{warmCacheStatus?.state || '-'}</strong>
            <small>{text.observability.models}: {(warmCacheStatus?.models || []).join(', ') || '-'}</small>
          </div>
          <div className="stat-card stat-card-default">
            <span>{text.observability.warmProgress}</span>
            <strong>{warmCacheStatus?.docs_processed ?? 0}/{warmCacheStatus?.docs_total ?? 0}</strong>
            <small>{text.observability.entriesWritten}: {warmCacheStatus?.entries_written ?? 0}</small>
          </div>
          <div className="stat-card stat-card-default">
            <span>{text.observability.semanticEntries}</span>
            <strong>{semanticCacheStats?.points ?? 0}</strong>
            <small>{semanticCacheStats?.collection || '-'}</small>
          </div>
        </div>
        {warmCacheMessage && (
          <p style={{ color: '#12715b', fontSize: '14px', marginTop: '8px' }}>{warmCacheMessage}</p>
        )}
        {(warmCacheStatus?.errors || []).length > 0 && (
          <p style={{ color: '#a40e26', fontSize: '13px', marginTop: '8px' }}>
            {text.observability.errors}: {(warmCacheStatus?.errors || []).join(' | ')}
          </p>
        )}
        {(warmCacheStatus?.recent_sources || []).length > 0 && (
          <div style={{ marginTop: '12px' }}>
            <h4 style={{ margin: '0 0 8px 0', fontSize: '13px', color: '#475467' }}>Recently Processed Documents</h4>
            <div className="scroll-region" style={{ maxHeight: '180px' }}>
              {(warmCacheStatus?.recent_sources || []).slice().reverse().map((source, idx) => (
                <div key={`${source}-${idx}`} style={{ fontSize: '12px', color: '#475467', marginBottom: '6px' }}>
                  {source}
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.observability.deployIntelligence}</p>
            <h3>{text.observability.deployIntelligenceTitle}</h3>
          </div>
          <div className="trace-toolbar">
            <button className="secondary-button" onClick={fetchDeployIntelStatus}>
              {text.observability.refreshStatus}
            </button>
          </div>
        </div>
        <div className="stats-grid">
          <div className="stat-card stat-card-default">
            <span>{text.observability.status}</span>
            <strong>{deployIntelStatus?.state || '-'}</strong>
            <small>{text.observability.currentStage}: {formatStageLabel(deployIntelStatus?.current_stage)}</small>
          </div>
          <div className="stat-card stat-card-default">
            <span>{text.observability.progress}</span>
            <strong>{deployIntelStatus?.completion_percent ?? 0}%</strong>
            <small>{text.observability.stages}: {(deployIntelStatus?.stages || []).length}/{deployIntelStatus?.total_stages ?? 5}</small>
          </div>
          <div className="stat-card stat-card-default">
            <span>{text.observability.runtime}</span>
            <strong>{deployIntelStatus?.last_run_seconds ?? 0}s</strong>
            <small>{text.observability.reportPath}: {deployIntelStatus?.report_path || '-'}</small>
          </div>
        </div>
        <div style={{ marginTop: '10px' }}>
          <progress
            max="100"
            value={Math.max(0, Math.min(100, Number(deployIntelStatus?.completion_percent || 0)))}
            style={{ width: '100%', height: '10px' }}
          />
        </div>
        {(deployIntelStatus?.errors || []).length > 0 && (
          <p style={{ color: '#a40e26', fontSize: '13px', marginTop: '8px' }}>
            {text.observability.errors}: {(deployIntelStatus?.errors || []).join(' | ')}
          </p>
        )}
        {(deployIntelStatus?.stages || []).length > 0 && (
          <div style={{ marginTop: '12px' }}>
            <h4 style={{ margin: '0 0 8px 0', fontSize: '13px', color: '#475467' }}>Live Stage Updates</h4>
            <div className="scroll-region" style={{ maxHeight: '220px' }}>
              {(deployIntelStatus?.stages || []).map((stage) => (
                <div key={stage.name} style={{ marginBottom: '8px', fontSize: '12px' }}>
                  <strong>{formatStageLabel(stage.name)}</strong>
                  <span style={{ marginLeft: '8px', color: '#667085' }}>{stage.state}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.observability.searchCache}</p>
            <h3>{text.observability.searchCacheTitle}</h3>
          </div>
          <button
            className="secondary-button"
            disabled={clearingSearchCache}
            onClick={clearRetrievalSearchCache}
          >
            {clearingSearchCache ? text.observability.clearing : text.observability.clearSearchCache}
          </button>
        </div>
        {searchCacheClearedMsg && (
          <p style={{ color: '#12715b', fontSize: '14px', marginTop: '8px' }}>{searchCacheClearedMsg}</p>
        )}
        <p style={{ color: '#666', fontSize: '14px', marginTop: '8px' }}>
          {text.observability.searchCacheDescription}
        </p>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.observability.recentTraces}</p>
            <h3>{text.observability.latestRuns}</h3>
          </div>
          <div className="trace-toolbar">
            <label htmlFor="trace-limit-select" className="trace-limit-label">
              {text.observability.traceLimitLabel}
            </label>
            <select
              id="trace-limit-select"
              className="trace-limit-select"
              value={langsmithTraceLimit}
              onChange={(event) => {
                const nextLimit = Number(event.target.value)
                setLangsmithTraceLimit(nextLimit)
              }}
              disabled={langsmithTracesLoading}
            >
              <option value={3}>3</option>
              <option value={10}>10</option>
              <option value={30}>30</option>
            </select>
          </div>
        </div>
        {langsmithTraces.length === 0 ? (
          <p className="empty-state">
            {langsmithTracesLoading ? text.observability.loadingTraces : text.observability.noRecentTraces}
          </p>
        ) : (
          <div className="scroll-region" style={{ maxHeight: '400px' }}>
            {langsmithTraces.map((trace) => (
              <article key={trace.id} className="review-card" style={{ padding: '12px', marginBottom: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
                  <div>
                    <strong>{trace.name}</strong>
                    <p style={{ fontSize: '12px', color: '#666', margin: '4px 0' }}>
                      {new Date(trace.created_at).toLocaleString()}
                    </p>
                    <p style={{ fontSize: '12px', color: '#999' }}>
                      ID: {trace.id || '-'}
                    </p>
                    {trace.id && (
                      <a
                        href={buildLangsmithTraceUrl(trace.id)}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ fontSize: '12px', textDecoration: 'none' }}
                      >
                        {text.observability.openTrace}
                      </a>
                    )}
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <span
                      style={{
                        display: 'inline-block',
                        padding: '4px 8px',
                        borderRadius: '4px',
                        backgroundColor: trace.status === 'success' ? '#e8f5e9' : '#fff3e0',
                        color: trace.status === 'success' ? '#12715b' : '#bf8f00',
                        fontSize: '12px',
                        fontWeight: '500',
                      }}
                    >
                      {trace.status}
                    </span>
                    {trace.duration_ms && (
                      <p style={{ fontSize: '12px', color: '#999', marginTop: '4px' }}>
                        {(trace.duration_ms / 1000).toFixed(1)}s
                      </p>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Token-Oriented Object Notation</p>
            <h3>Prompt Usage Telemetry</h3>
          </div>
          <button
            className="secondary-button"
            disabled={promptUsageLoading}
            onClick={fetchPromptUsage}
          >
            {promptUsageLoading ? text.observability.loading : text.observability.refreshStatus ?? 'Refresh'}
          </button>
        </div>
        {promptUsageLoading && <p className="empty-state">{text.observability.loading}</p>}
        {!promptUsageLoading && promptUsage && (
          <>
            <div className="stats-grid">
              <div className="stat-card stat-card-default">
                <span>Catalog Prompts</span>
                <strong>{promptUsage.catalog_prompt_count ?? 0}</strong>
              </div>
              <div className="stat-card stat-card-default">
                <span>Unique Renders</span>
                <strong>{promptUsage.unique_prompts_rendered ?? 0}</strong>
              </div>
              <div className="stat-card stat-card-default">
                <span>Total Events</span>
                <strong>{promptUsage.render_events_analyzed ?? 0}</strong>
              </div>
            </div>
            {(promptUsage.prompts || []).length > 0 ? (
              <div style={{ marginTop: '16px' }}>
                <h4 style={{ margin: '0 0 12px 0', fontSize: '13px', color: '#475467' }}>Top Prompts by Render Count</h4>
                <div className="scroll-region" style={{ maxHeight: '400px' }}>
                  {promptUsage.prompts.map((prompt) => (
                    <div
                      key={prompt.prompt_id}
                      style={{
                        marginBottom: '12px',
                        padding: '12px',
                        borderRadius: '10px',
                        border: '1px solid #e2e8ee',
                        background: '#fcfdfe',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: '8px' }}>
                        <div style={{ flex: '1', minWidth: '0' }}>
                          <strong style={{ color: '#10212d', wordBreak: 'break-word' }}>{prompt.prompt_id}</strong>
                          <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#5f6973' }}>
                            {prompt.why || '(No description)'}
                          </p>
                          <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#8a9db1' }}>
                            Owner: {prompt.owner || '-'}
                          </p>
                        </div>
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginTop: '8px', fontSize: '12px', color: '#6a7480' }}>
                        <span>
                          <strong>{prompt.renders ?? 0}</strong> renders
                        </span>
                        <span>
                          <strong>{prompt.estimated_tokens_total ?? 0}</strong> tokens
                        </span>
                        <span>
                          <strong>{prompt.avg_rendered_chars ?? 0}</strong> avg chars
                        </span>
                        {prompt.last_seen && (
                          <span style={{ color: '#98a2b3' }}>
                            Last: {new Date(prompt.last_seen).toLocaleTimeString()}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="empty-state">No prompt render events yet. Run a retrieval query to generate telemetry.</p>
            )}
          </>
        )}
      </section>
    </>
  )
}
