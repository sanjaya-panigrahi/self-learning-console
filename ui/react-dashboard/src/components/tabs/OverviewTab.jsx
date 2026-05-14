export default function OverviewTab({
  text,
  ready,
  report,
  retrievalOverview,
  wikiIndex,
  warmCacheStatus,
  semanticCacheStats,
  deployIntelStatus,
  langsmithStatus,
  evaluationSummary,
  formatStageLabel,
}) {
  const StatCard = ({ label, value, tone = 'default' }) => (
    <div className={`stat-card stat-card-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )

  return (
    <>
      <section className="hero-card">
        <div>
          <p className="eyebrow">{text.overview.systemStatus}</p>
          <h2>{ready?.status || 'loading'}</h2>
          <p className="meta-line">
            {text.overview.source}: {report?.source_dir || '-'}
            <span>{text.overview.vectorBackend}: {report?.vector_backend || '-'}</span>
          </p>
        </div>
        <div className="component-grid">
          {Object.entries(ready?.components || {}).map(([name, component]) => (
            <div key={name} className="component-card">
              <span>{name}</span>
              <strong>{component.status}</strong>
              <small>{component.reason || `HTTP ${component.status_code || '-'}`}</small>
            </div>
          ))}
        </div>
      </section>

      <section className="stats-grid">
        <StatCard label={text.overview.stats.processedFiles} value={report?.processed_files ?? '-'} />
        <StatCard label={text.overview.stats.indexedChunks} value={report?.indexed_chunks ?? '-'} tone="success" />
        <StatCard
          label={text.overview.stats.piiDetected}
          value={report?.password_detected_files ?? report?.pii_detected_files ?? '-'}
          tone="warning"
        />
        <StatCard label={text.overview.stats.pendingReview} value={report?.pending_review_files ?? '-'} tone="danger" />
      </section>

      <section className="stats-grid retrieval-stats-grid">
        <StatCard label={text.overview.stats.materialLibrary} value={retrievalOverview?.material_count ?? '-'} />
        <StatCard
          label={text.overview.stats.searchableItems}
          value={retrievalOverview?.searchable_material_count ?? '-'}
          tone="success"
        />
        <StatCard label={text.overview.stats.blockedMaterials} value={retrievalOverview?.blocked_material_count ?? '-'} tone="warning" />
        <StatCard
          label={text.overview.stats.failedMaterials}
          value={retrievalOverview?.failed_material_count ?? '-'}
          tone="danger"
        />
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.observability.semanticWarmCache}</p>
            <h3>{text.observability.semanticWarmCacheTitle}</h3>
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
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.observability.deployIntelligence}</p>
            <h3>{text.observability.deployIntelligenceTitle}</h3>
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
            <small>{deployIntelStatus?.report_path ? 'Complete' : 'In progress'}</small>
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
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.observability.evaluation}</p>
            <h3>{text.observability.qualityChecks}</h3>
          </div>
        </div>
        {evaluationSummary && (
          <div className="stats-grid">
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

      <section className="stats-grid retrieval-stats-grid">
        <StatCard label={text.wiki.sourcePages} value={wikiIndex?.source_count ?? '-'} />
        <StatCard label={text.wiki.entityPages} value={wikiIndex?.entity_count ?? '-'} />
        <StatCard label={text.wiki.conceptPages} value={wikiIndex?.concept_count ?? '-'} />
        <div className="stat-card stat-card-default">
          <span>{text.wiki.wikiDir}</span>
          <strong style={{ fontSize: '11px', wordBreak: 'break-all' }}>{wikiIndex?.wiki_dir ?? '-'}</strong>
        </div>
      </section>

      {langsmithStatus?.enabled && (
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Observability</p>
              <h3>{text.observability.langsmithIntegration}</h3>
            </div>
            <span style={{ color: '#12715b', fontWeight: '500' }}>● {text.observability.active}</span>
          </div>
          <p style={{ color: '#666', fontSize: '14px' }}>
            {text.observability.projectName}: <strong>{langsmithStatus?.project || 'self-learning-console'}</strong>
          </p>
          {langsmithStatus?.project && (
            <a
              href={`https://smith.langchain.com/projects/p?name=${langsmithStatus.project}`}
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontSize: '14px', textDecoration: 'none', color: '#0066cc' }}
            >
              {text.observability.openLangsmith} →
            </a>
          )}
        </section>
      )}
    </>
  )
}
