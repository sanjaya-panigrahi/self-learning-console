import { useEffect, useRef, useState } from 'react'
import uiText from './config/uiText.json'
import IngestionTab from './components/tabs/IngestionTab'
import OverviewTab from './components/tabs/OverviewTab'
import RetrievalTab from './components/tabs/RetrievalTab'
import WikiTab from './components/tabs/WikiTab'
import {
  RETRIEVAL_SEARCH_STORAGE_KEY,
  extractQueryKeywords,
  extractStructuredSummarySections,
  filterWikiPages,
  findMatchingWikiTarget,
  formatStageLabel,
  getSummaryFormatFlags,
  isResultRelevant,
  normalizeQuestionKey,
  normalizeTab,
  readRetrievalSearchFromStorage,
  readRetrievalSearchFromUrl,
  readTabFromUrl,
} from './utils/dashboardUtils'

export {
  extractStructuredSummarySections,
  getSummaryFormatFlags,
  normalizeTab,
  readRetrievalSearchFromUrl,
  readTabFromUrl,
}

const DASHBOARD_MODES = {
  admin: 'admin',
  user: 'user',
}

const getAllowedTabs = (mode) =>
  mode === DASHBOARD_MODES.admin
    ? ['overview', 'ingestion', 'retrieval', 'knowledge-search', 'wiki']
    : ['overview', 'retrieval', 'knowledge-search', 'wiki']

const getDefaultTabForMode = (mode) => (mode === DASHBOARD_MODES.admin ? 'overview' : 'knowledge-search')

const readDashboardModeFromUrl = () => {
  if (typeof window === 'undefined') {
    return DASHBOARD_MODES.user
  }

  const pathname = String(window.location.pathname || '').toLowerCase()
  if (pathname.includes('/dashboard/admin')) {
    return DASHBOARD_MODES.admin
  }
  if (pathname.includes('/dashboard/user')) {
    return DASHBOARD_MODES.user
  }

  const params = new URLSearchParams(window.location.search)
  const modeFromQuery = String(params.get('mode') || '').toLowerCase()
  if (modeFromQuery === DASHBOARD_MODES.admin) {
    return DASHBOARD_MODES.admin
  }
  if (modeFromQuery === DASHBOARD_MODES.user) {
    return DASHBOARD_MODES.user
  }

  return DASHBOARD_MODES.user
}

const apiFetch = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Request failed: ${response.status}`)
  }

  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return response.json()
  }
  return response.text()
}

const StatCard = ({ label, value, tone = 'default' }) => (
  <div className={`stat-card stat-card-${tone}`}>
    <span>{label}</span>
    <strong>{value}</strong>
  </div>
)

const Badge = ({ value }) => <span className={`badge badge-${value}`}>{value}</span>

const VisualReferenceCard = ({ item, onViewPdf }) => (
  <article className="visual-reference-card">
    <div className="visual-reference-preview">
      {item.preview_url ? (
        <img src={item.preview_url} alt={`${item.source} preview`} loading="lazy" />
      ) : (
        <div className="visual-reference-fallback">Preview unavailable</div>
      )}
    </div>
    <div className="visual-reference-body">
      <strong>{item.source}</strong>
      <p>{item.note || 'Preview generated from the cited guide.'}</p>
      {item.document_url && (
        <button
          className="ghost-inline-button visual-reference-link"
          onClick={() => {
            if (item.source.endsWith('.pdf') && onViewPdf) {
              onViewPdf(item.document_url)
            } else {
              window.open(item.document_url, '_blank', 'noreferrer')
            }
          }}
        >
          Open guide
        </button>
      )}
    </div>
  </article>
)

const MaterialCard = ({ item, onInspect }) => (
  <article className="material-card">
    <div className="material-card-head">
      <div>
        <strong>{item.source}</strong>
        <p>{item.preview || 'No preview available. This item may still be blocked or failed.'}</p>
      </div>
      <Badge value={item.status} />
    </div>
    <div className="material-meta">
      <span>{item.chunk_count} chunks</span>
      <span>{item.reason}</span>
    </div>
    {(item.sample_chunks || []).length > 0 && (
      <div className="sample-list">
        {item.sample_chunks.map((chunk, index) => (
          <div key={`${item.source}-${index}`} className="sample-chip">{chunk}</div>
        ))}
      </div>
    )}
    <div className="material-actions">
      <button className="ghost-inline-button" onClick={() => onInspect(item.source)}>
        Inspect With AI
      </button>
    </div>
  </article>
)


function App() {
  const text = uiText
  const [dashboardMode, setDashboardMode] = useState(() => readDashboardModeFromUrl())
  const isAdminView = dashboardMode === DASHBOARD_MODES.admin
  const [report, setReport] = useState(null)
  const [ready, setReady] = useState(null)
  const [activeTab, setActiveTab] = useState(() => {
    const initialMode = readDashboardModeFromUrl()
    const allowedTabs = getAllowedTabs(initialMode)
    if (typeof window === 'undefined') {
      return getDefaultTabForMode(initialMode)
    }

    const tabFromUrl = readTabFromUrl()
    if (tabFromUrl && allowedTabs.includes(tabFromUrl)) {
      return tabFromUrl
    }

    return getDefaultTabForMode(initialMode)
  })
  const [retrievalOverview, setRetrievalOverview] = useState(null)
  const [retrievalSearch, setRetrievalSearch] = useState(() => {
    const searchFromUrl = readRetrievalSearchFromUrl()
    if (searchFromUrl) {
      return searchFromUrl
    }
    return readRetrievalSearchFromStorage()
  })
  const [retrievalResults, setRetrievalResults] = useState(null)
  const [retrievalToast, setRetrievalToast] = useState('')
  const [retrievalLoading, setRetrievalLoading] = useState(false)
  const [showKnowledgeSearch, setShowKnowledgeSearch] = useState(false)
  const [showImportantInformation, setShowImportantInformation] = useState(false)
  const toggleImportantInformation = () => {
    setShowImportantInformation((current) => {
      const next = !current
      if (next) {
        setShowKnowledgeSearch(false)
      }
      return next
    })
  }
  const toggleKnowledgeSearch = () => {
    setShowKnowledgeSearch((current) => {
      const next = !current
      if (next) {
        setShowImportantInformation(false)
      }
      return next
    })
  }
  const [selectedMaterial, setSelectedMaterial] = useState('')
  const [materialInsight, setMaterialInsight] = useState(null)
  const [materialInsightLoading, setMaterialInsightLoading] = useState(false)
  const [hasAttemptedRestoreInsight, setHasAttemptedRestoreInsight] = useState(false)
  const materialInsightRequestRef = useRef(0)
  const previousIngestionStateRef = useRef('idle')
  const [selectedCoverageSource, setSelectedCoverageSource] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionMessage, setActionMessage] = useState('')
  const [ingestionStatus, setIngestionStatus] = useState(null)
  const [lightboxImage, setLightboxImage] = useState(null)
  const [pdfViewerUrl, setPdfViewerUrl] = useState(null)
  const [feedbackSessionId, setFeedbackSessionId] = useState('')
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false)
  const [feedbackRecorded, setFeedbackRecorded] = useState(null)
  const [feedbackSummary, setFeedbackSummary] = useState(null)
  const [feedbackSummaryLoading, setFeedbackSummaryLoading] = useState(false)
  const [answerFiled, setAnswerFiled] = useState(false)
  const [uiAlignedQaItems, setUiAlignedQaItems] = useState([])
  const [selectedSuggestedQa, setSelectedSuggestedQa] = useState(null)
  const [evaluationSummary, setEvaluationSummary] = useState(null)
  const [evaluationLoading, setEvaluationLoading] = useState(false)
  const [langsmithStatus, setLangsmithStatus] = useState(null)
  const [langsmithTraces, setLangsmithTraces] = useState([])
  const [langsmithTracesLoading, setLangsmithTracesLoading] = useState(false)
  const [langsmithTraceLimit, setLangsmithTraceLimit] = useState(3)
  const [clearingSearchCache, setClearingSearchCache] = useState(false)
  const [searchCacheClearedMsg, setSearchCacheClearedMsg] = useState(null)
  const [warmCacheStatus, setWarmCacheStatus] = useState(null)
  const [semanticCacheStats, setSemanticCacheStats] = useState(null)
  const [warmCacheActionLoading, setWarmCacheActionLoading] = useState(false)
  const [warmCacheMessage, setWarmCacheMessage] = useState('')
  const [deployIntelStatus, setDeployIntelStatus] = useState(null)
  const [wikiIndex, setWikiIndex] = useState(null)
  const [wikiPage, setWikiPage] = useState(null) // { kind, name, content }
  const [wikiLoading, setWikiLoading] = useState(false)
  const [wikiImpact, setWikiImpact] = useState(null)
  const [wikiReviewSubmitting, setWikiReviewSubmitting] = useState(false)
  const [wikiImpactFilter, setWikiImpactFilter] = useState('all')
  const [wikiSearchTerm, setWikiSearchTerm] = useState('')
  const [promptUsage, setPromptUsage] = useState(null)
  const [promptUsageLoading, setPromptUsageLoading] = useState(false)

  useEffect(() => {
    if (typeof document !== 'undefined' && uiText?.documentTitle) {
      document.title = uiText.documentTitle
    }
  }, [])

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        setLightboxImage(null)
        setPdfViewerUrl(null)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    const syncFromUrl = () => {
      const modeFromUrl = readDashboardModeFromUrl()
      setDashboardMode(modeFromUrl)

      const allowedTabs = getAllowedTabs(modeFromUrl)
      const tabFromUrl = readTabFromUrl()
      if (tabFromUrl && allowedTabs.includes(tabFromUrl) && tabFromUrl !== activeTab) {
        setActiveTab(tabFromUrl)
      }
      if ((!tabFromUrl || !allowedTabs.includes(tabFromUrl)) && !allowedTabs.includes(activeTab)) {
        setActiveTab(getDefaultTabForMode(modeFromUrl))
      }

      const searchFromUrl = readRetrievalSearchFromUrl()
      if (searchFromUrl) {
        setRetrievalSearch(searchFromUrl)
      }
    }
    if (typeof window !== 'undefined') {
      window.addEventListener('popstate', syncFromUrl)
    }
    return () => {
      if (typeof window !== 'undefined') {
        window.removeEventListener('popstate', syncFromUrl)
      }
    }
  }, [activeTab])

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search)
      params.set('tab', activeTab)
      params.set('mode', dashboardMode)

      const nextQuery = retrievalSearch.query.trim()
      const nextDomainContext = retrievalSearch.domain_context.trim()
      if (nextQuery) {
        params.set('query', nextQuery)
      } else {
        params.delete('query')
      }
      if (nextDomainContext) {
        params.set('domainContext', nextDomainContext)
        params.set('domain_context', nextDomainContext)
      } else {
        params.delete('domainContext')
        params.delete('domain_context')
      }

      const nextPath = dashboardMode === DASHBOARD_MODES.admin ? '/dashboard/admin' : '/dashboard/user'
      const nextUrl = `${nextPath}?${params.toString()}`
      window.history.replaceState({}, '', nextUrl)
    }
  }, [activeTab, dashboardMode, retrievalSearch])

  useEffect(() => {
    const allowedTabs = getAllowedTabs(dashboardMode)
    if (!allowedTabs.includes(activeTab)) {
      setActiveTab(getDefaultTabForMode(dashboardMode))
    }
  }, [dashboardMode, activeTab])

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(RETRIEVAL_SEARCH_STORAGE_KEY, JSON.stringify(retrievalSearch))
    }
  }, [retrievalSearch])

  useEffect(() => {
    if (!retrievalToast) {
      return
    }
    const timeoutId = window.setTimeout(() => {
      setRetrievalToast('')
    }, 2800)
    return () => window.clearTimeout(timeoutId)
  }, [retrievalToast])

  useEffect(() => {
    if (activeTab === 'knowledge-search') {
      setShowKnowledgeSearch(true)
      return
    }
    if (activeTab === 'retrieval') {
      setShowImportantInformation(true)
    }
  }, [activeTab])

  const loadDashboard = async () => {
    setLoading(true)
    try {
      const [reportData, readyData, retrievalData, wikiIndexData, alignedQaData, ingestionStatusData] = await Promise.all([
        apiFetch('/api/admin/report'),
        apiFetch('/api/ready'),
        apiFetch('/api/admin/retrieval-overview'),
        apiFetch('/api/admin/wiki/index'),
        apiFetch('/api/admin/wiki/ui-aligned-qa'),
        apiFetch('/api/admin/ingestion/status'),
      ])
      setReport(reportData)
      setReady(readyData)
      setRetrievalOverview(retrievalData)
      setWikiIndex(wikiIndexData)
      setUiAlignedQaItems(Array.isArray(alignedQaData?.items) ? alignedQaData.items : [])
      setIngestionStatus(ingestionStatusData)
    } catch (error) {
      setActionMessage(error.message)
    } finally {
      setLoading(false)
    }
  }

  const fetchIngestionStatus = async () => {
    try {
      const result = await apiFetch('/api/admin/ingestion/status')
      setIngestionStatus(result)
      return result
    } catch (error) {
      setActionMessage(error.message)
      return null
    }
  }

  useEffect(() => {
    loadDashboard()
  }, [])

  const triggerReindex = async () => {
    setActionMessage('Running reindex...')
    try {
      const result = await apiFetch('/api/admin/reindex', { method: 'POST' })
      if (result.status === 'already_running') {
        setActionMessage('Reindex already running. Showing live progress...')
      } else {
        setActionMessage('Reindex started. Showing live progress...')
      }
      await fetchIngestionStatus()
      await loadDashboard()
    } catch (error) {
      setActionMessage(error.message)
    }
  }

  const switchDashboardMode = (nextMode) => {
    if (nextMode !== DASHBOARD_MODES.admin && nextMode !== DASHBOARD_MODES.user) {
      return
    }
    const allowedTabs = getAllowedTabs(nextMode)
    setDashboardMode(nextMode)
    if (!allowedTabs.includes(activeTab)) {
      setActiveTab(getDefaultTabForMode(nextMode))
    }
  }

  const executeRetrievalSearch = async ({ queryOverride = null, preserveSelectedQa = false } = {}) => {
    const effectiveQuery = String(queryOverride ?? retrievalSearch.query).trim()
    if (!effectiveQuery) {
      setActionMessage('Enter a retrieval question or topic to inspect indexed material.')
      return null
    }

    setRetrievalLoading(true)
    setFeedbackSubmitting(false)
    setFeedbackRecorded(null)
    setAnswerFiled(false)
    if (!preserveSelectedQa) {
      setSelectedSuggestedQa(null)
    }
    setActionMessage('Searching indexed material...')
    try {
      const result = await apiFetch('/api/admin/retrieval-search', {
        method: 'POST',
        body: JSON.stringify({
          query: effectiveQuery,
          domain_context: retrievalSearch.domain_context,
          top_k: 6,
        }),
      })
      setRetrievalResults(result)
      setFeedbackSessionId(
        `retrieval-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      )
      setActionMessage(`Retrieved ${result.result_count} relevant passages.`)
      return result
    } catch (error) {
      setActionMessage(error.message)
      return null
    } finally {
      setRetrievalLoading(false)
    }
  }

  const runRetrievalSearch = async () => {
    await executeRetrievalSearch()
  }

  const fetchFeedbackSummary = async () => {
    setFeedbackSummaryLoading(true)
    try {
      const result = await apiFetch('/api/admin/feedback-summary?limit=200')
      setFeedbackSummary(result)
    } catch (error) {
      setActionMessage(error.message)
    } finally {
      setFeedbackSummaryLoading(false)
    }
  }

  const fetchEvaluationSummary = async () => {
    setEvaluationLoading(true)
    try {
      const result = await apiFetch('/api/admin/evaluation-summary?limit=200')
      setEvaluationSummary(result)
    } catch (error) {
      setActionMessage(error.message)
      setEvaluationSummary(null)
    } finally {
      setEvaluationLoading(false)
    }
  }

  const fetchLangsmithStatus = async () => {
    try {
      const result = await apiFetch('/api/admin/observability-status')
      setLangsmithStatus(result?.langsmith)
    } catch (error) {
      setActionMessage(error.message)
    }
  }

  const fetchLangsmithTraces = async (limit = langsmithTraceLimit) => {
    setLangsmithTracesLoading(true)
    try {
      const result = await apiFetch(`/api/admin/langsmith-traces?limit=${encodeURIComponent(limit)}`)
      setLangsmithTraces(result?.traces || [])
    } catch (error) {
      setActionMessage(error.message)
      setLangsmithTraces([])
    } finally {
      setLangsmithTracesLoading(false)
    }
  }

  const fetchWarmCacheStatus = async () => {
    try {
      const [statusResult, statsResult] = await Promise.all([
        apiFetch('/api/admin/warm-cache/status'),
        apiFetch('/api/admin/semantic-cache/stats'),
      ])
      setWarmCacheStatus(statusResult)
      setSemanticCacheStats(statsResult)
    } catch (error) {
      setActionMessage(error.message)
    }
  }

  const fetchDeployIntelStatus = async () => {
    try {
      const statusResult = await apiFetch('/api/admin/deploy-intelligence/status')
      setDeployIntelStatus(statusResult)
    } catch (error) {
      setActionMessage(error.message)
    }
  }

  const fetchWikiIndex = async ({ resetPage = true } = {}) => {
    setWikiLoading(true)
    try {
      const [result, impactResult] = await Promise.all([
        apiFetch('/api/admin/wiki/index'),
        apiFetch('/api/admin/wiki/impact-report'),
      ])
      setWikiIndex(result)
      setWikiImpact(impactResult)
      if (resetPage) {
        setWikiPage(null)
      }
    } catch (error) {
      setActionMessage(error.message)
    } finally {
      setWikiLoading(false)
    }
  }

  const handleSuggestedQuestionSelect = async (question) => {
    const normalized = normalizeQuestionKey(question)
    const match = uiAlignedQaItems.find(
      (item) => normalizeQuestionKey(item?.question) === normalized,
    )

    setRetrievalSearch((current) => ({
      ...current,
      query: question,
    }))

    if (match?.answer) {
      setSelectedSuggestedQa({ question: match.question, answer: match.answer })
    } else {
      setSelectedSuggestedQa({ question, answer: '' })
    }

    const result = await executeRetrievalSearch({ queryOverride: question, preserveSelectedQa: true })
    const liveAnswer = String(result?.answer || '').trim()
    if (liveAnswer) {
      const normalizedQuestion = normalizeQuestionKey(question)
      setSelectedSuggestedQa((current) => {
        if (!current || normalizeQuestionKey(current.question) !== normalizedQuestion) {
          return current
        }
        return {
          ...current,
          answer: liveAnswer,
        }
      })
    }
  }

  const fetchWikiPage = async (kind, name) => {
    setWikiLoading(true)
    try {
      const result = await apiFetch(`/api/admin/wiki/page?kind=${encodeURIComponent(kind)}&name=${encodeURIComponent(name)}`)
      setWikiPage(result)
    } catch (error) {
      setActionMessage(error.message)
    } finally {
      setWikiLoading(false)
    }
  }

  const openWikiSourceFromRetrieval = async (source) => {
    const target = findMatchingWikiTarget(source, wikiIndex)
    if (!target) {
      setActionMessage('No matching wiki page found for this citation.')
      return
    }
    setActiveTab('wiki')
    await fetchWikiPage(target.kind, target.name)
  }

  const updateWikiReviewState = async (status) => {
    if (!wikiPage?.kind || !wikiPage?.name) {
      return
    }
    setWikiReviewSubmitting(true)
    try {
      const result = await apiFetch('/api/admin/wiki/review-state', {
        method: 'POST',
        body: JSON.stringify({
          kind: wikiPage.kind,
          name: wikiPage.name,
          status,
          reviewer: 'dashboard-user',
          notes: `Set via dashboard on ${new Date().toISOString()}`,
        }),
      })
      setWikiPage((prev) => {
        if (!prev) {
          return prev
        }
        return {
          ...prev,
          review: result.review,
        }
      })
      if (result.summary) {
        setWikiIndex((prev) => {
          if (!prev) {
            return prev
          }
          return {
            ...prev,
            review_summary: result.summary,
          }
        })
      }
      setActionMessage(`Review status updated to ${status}.`)
    } catch (error) {
      setActionMessage(error.message)
    } finally {
      setWikiReviewSubmitting(false)
    }
  }

  const openImpactPage = async (relativePath) => {
    if (!relativePath || typeof relativePath !== 'string') {
      return
    }
    const clean = relativePath.trim().replace(/^\/+/, '')
    const parts = clean.split('/')
    if (parts.length < 2) {
      return
    }
    const folder = parts[0]
    const fileName = parts[parts.length - 1]
    const name = fileName.replace(/\.md$/i, '')
    const kindMap = {
      sources: 'source',
      entities: 'entity',
      concepts: 'concept',
      answers: 'answer',
    }
    const kind = kindMap[folder]
    if (!kind || !name) {
      return
    }
    await fetchWikiPage(kind, name)
  }

  const showImpactBucket = (bucket) => {
    if (wikiImpactFilter === 'all') {
      return true
    }
    return wikiImpactFilter === bucket
  }

  const runWarmCache = async () => {
    setWarmCacheActionLoading(true)
    try {
      const result = await apiFetch('/api/admin/warm-cache/run', {
        method: 'POST',
        body: JSON.stringify({ force: false }),
      })
      if (result?.status === 'blocked_by_indexing') {
        setWarmCacheMessage(result?.detail?.message || 'Warm cache is blocked until indexing completes.')
      } else {
        setWarmCacheMessage(result?.status === 'already_running'
          ? text.observability.warmCacheAlreadyRunning
          : text.observability.warmCacheTriggered)
      }
      await fetchWarmCacheStatus()
    } catch (error) {
      setWarmCacheMessage(error.message)
    } finally {
      setWarmCacheActionLoading(false)
    }
  }

  const clearSemanticCache = async () => {
    setWarmCacheActionLoading(true)
    try {
      await apiFetch('/api/admin/semantic-cache/clear', { method: 'POST' })
      setWarmCacheMessage(text.observability.semanticCacheCleared)
      await fetchWarmCacheStatus()
    } catch (error) {
      setWarmCacheMessage(error.message)
    } finally {
      setWarmCacheActionLoading(false)
    }
  }

  const clearRetrievalSearchCache = async () => {
    setClearingSearchCache(true)
    setSearchCacheClearedMsg(null)
    try {
      await apiFetch('/api/admin/retrieval-search-cache/clear', { method: 'POST' })
      setSearchCacheClearedMsg(text.observability.searchCacheCleared)
    } catch {
      setSearchCacheClearedMsg(text.observability.searchCacheClearFailed)
    } finally {
      setClearingSearchCache(false)
    }
  }

  const fetchPromptUsage = async () => {
    setPromptUsageLoading(true)
    try {
      const result = await apiFetch('/api/admin/prompt-usage?limit=2000')
      setPromptUsage(result)
    } catch (error) {
      setActionMessage(error.message)
    } finally {
      setPromptUsageLoading(false)
    }
  }

  useEffect(() => {
    fetchLangsmithStatus()
    if (activeTab === 'wiki') {
      fetchWikiIndex({ resetPage: false })
    }
  }, [activeTab, langsmithTraceLimit])

  useEffect(() => {
    if (activeTab !== 'overview') {
      return undefined
    }

    const intervalId = window.setInterval(() => {
      fetchWarmCacheStatus()
      fetchDeployIntelStatus()
      fetchPromptUsage()
    }, 2500)

    return () => window.clearInterval(intervalId)
  }, [activeTab])

  useEffect(() => {
    if (activeTab !== 'ingestion') {
      return undefined
    }

    fetchIngestionStatus()

    const intervalId = window.setInterval(async () => {
      const status = await fetchIngestionStatus()
      if (status?.state && status.state !== 'running') {
        await loadDashboard()
      }
    }, 2000)

    return () => window.clearInterval(intervalId)
  }, [activeTab])

  useEffect(() => {
    const state = String(ingestionStatus?.state || '').toLowerCase()
    const previous = String(previousIngestionStateRef.current || '').toLowerCase()

    if (!state) {
      return
    }

    if (previous === 'running' && state !== 'running') {
      loadDashboard()
    }

    previousIngestionStateRef.current = state
  }, [ingestionStatus?.state])

  useEffect(() => {
    if (String(ingestionStatus?.state || '').toLowerCase() !== 'running') {
      return undefined
    }

    const intervalId = window.setInterval(async () => {
      await fetchIngestionStatus()
    }, 2000)

    return () => window.clearInterval(intervalId)
  }, [ingestionStatus?.state])

  const submitRetrievalFeedback = async (helpful) => {
    if (!retrievalResults?.answer) {
      return
    }

    const uniqueSources = [...new Set((retrievalResults.results || []).map((item) => item.source).filter(Boolean))]

    setFeedbackSubmitting(true)
    try {
      const result = await apiFetch('/api/admin/feedback', {
        method: 'POST',
        body: JSON.stringify({
          session_id: feedbackSessionId || `retrieval-${Date.now()}`,
          helpful,
          query: retrievalSearch.query,
          retrieval_query: retrievalResults.retrieval_query,
          answer_model: retrievalResults.answer_model,
          answer_confidence: Number(retrievalResults.answer_confidence || 0),
          result_count: Number(retrievalResults.result_count || 0),
          sources: uniqueSources.slice(0, 8),
          answer: helpful ? retrievalResults.answer : undefined,
        }),
      })
      setFeedbackRecorded(helpful)
      setActionMessage(`Feedback ${result.status}. Thank you.`)
      await fetchFeedbackSummary()
    } catch (error) {
      setActionMessage(error.message)
    } finally {
      setFeedbackSubmitting(false)
    }
  }

  const fileAnswerToWiki = async () => {
    if (!retrievalResults?.answer || !retrievalSearch?.query) {
      return
    }
    const uniqueSources = [...new Set((retrievalResults.results || []).map((item) => item.source).filter(Boolean))]
    try {
      await apiFetch('/api/admin/wiki/file-answer', {
        method: 'POST',
        body: JSON.stringify({
          question: retrievalSearch.query,
          answer: retrievalResults.answer,
          confidence: Number(retrievalResults.answer_confidence || 0),
          sources: uniqueSources.slice(0, 8),
          session_id: feedbackSessionId || null,
        }),
      })
      setAnswerFiled(true)
      setActionMessage('Answer filed to wiki.')
      await fetchWikiIndex()
    } catch (error) {
      setActionMessage(error.message)
    }
  }

  useEffect(() => {
    if (activeTab !== 'retrieval') {
      return
    }
    fetchFeedbackSummary()
  }, [activeTab])

  const fetchMaterialInsight = async (source, { announce = true } = {}) => {
    const requestId = materialInsightRequestRef.current + 1
    materialInsightRequestRef.current = requestId
    setMaterialInsightLoading(true)
    if (announce) {
      setActionMessage(`Analyzing ${source}...`)
    }
    try {
      let receivedResult = null
      let timeoutNoticeShown = false
      const streamController = new AbortController()
      const streamTimeout = window.setTimeout(() => {
        streamController.abort()
      }, 240000)

      try {
        const response = await fetch('/api/admin/material-insight-stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: streamController.signal,
          body: JSON.stringify({
            source,
            domain_context: retrievalSearch.domain_context,
            use_cache: true,
          }),
        })

        if (!response.ok || !response.body) {
          throw new Error(`Streaming request failed: ${response.status}`)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        const applyEvent = (eventName, payload) => {
          if (requestId !== materialInsightRequestRef.current) {
            return
          }
          if (eventName === 'cache_hit') {
            setActionMessage(`Loaded cached insight for ${source}.`)
          }
          if (eventName === 'generating') {
            const model = payload?.model || 'local model'
            setActionMessage(`Analyzing ${source} with ${model}...`)
          }
          if (eventName === 'timeout_partial') {
            if (!timeoutNoticeShown) {
              timeoutNoticeShown = true
              setActionMessage(`Primary insight pass for ${source} exceeded its time budget; trying reduced prompt budgets.`)
            }
          }
          if (eventName === 'fallback' && payload?.reason === 'ollama_timeout') {
            setActionMessage(`Primary model timed out after retries for ${source}; continuing with best available summary and question generation.`)
          }
          if (eventName === 'result') {
            receivedResult = payload
            setMaterialInsight(payload)
          }
          if (eventName === 'error') {
            throw new Error(payload?.message || 'Insight stream failed')
          }
        }

        while (true) {
          const { done, value } = await reader.read()
          if (done) {
            break
          }

          buffer += decoder.decode(value, { stream: true })
          const frames = buffer.split('\n\n')
          buffer = frames.pop() || ''

          for (const frame of frames) {
            if (!frame.trim()) {
              continue
            }
            const lines = frame.split('\n')
            const eventLine = lines.find((line) => line.startsWith('event:'))
            const dataLine = lines.find((line) => line.startsWith('data:'))
            const eventName = eventLine ? eventLine.replace('event:', '').trim() : 'message'
            let payload = {}
            if (dataLine) {
              const raw = dataLine.replace('data:', '').trim()
              if (raw) {
                try {
                  payload = JSON.parse(raw)
                } catch {
                  payload = {}
                }
              }
            }
            applyEvent(eventName, payload)
          }
        }
      } catch (streamError) {
        if (streamError?.name === 'AbortError') {
          setActionMessage(`Insight streaming window was reached for ${source}; retrying with direct insight endpoint.`)
        } else {
          throw streamError
        }
      } finally {
        window.clearTimeout(streamTimeout)
      }

      if (!receivedResult) {
        const fallbackController = new AbortController()
        const fallbackTimeout = window.setTimeout(() => {
          fallbackController.abort()
        }, 180000)
        let result
        try {
          const fallbackResponse = await fetch('/api/admin/material-insight', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: fallbackController.signal,
            body: JSON.stringify({
              source,
              domain_context: retrievalSearch.domain_context,
              use_cache: true,
            }),
          })

          if (!fallbackResponse.ok) {
            const text = await fallbackResponse.text()
            throw new Error(text || `Request failed: ${fallbackResponse.status}`)
          }

          result = await fallbackResponse.json()
        } catch (fallbackError) {
          if (fallbackError?.name === 'AbortError') {
            throw new Error(`Insight fallback timed out for ${source}.`)
          }
          throw fallbackError
        } finally {
          window.clearTimeout(fallbackTimeout)
        }

        receivedResult = result
        if (requestId === materialInsightRequestRef.current) {
          setMaterialInsight(result)
        }
      }

      if (announce && requestId === materialInsightRequestRef.current) {
        const generationMs = Number(receivedResult?.generation_ms || 0)
        const fromCache = Boolean(receivedResult?.cached)
        if (fromCache) {
          setActionMessage(`Generated insight for ${source} from cache.`)
        } else if (generationMs > 0) {
          setActionMessage(`Generated insight for ${source} in ${(generationMs / 1000).toFixed(1)}s.`)
        } else {
          setActionMessage(`Generated insight for ${source}.`)
        }
      }
    } catch (error) {
      if (requestId === materialInsightRequestRef.current) {
        setActionMessage(error.message)
      }
    } finally {
      if (requestId === materialInsightRequestRef.current) {
        setMaterialInsightLoading(false)
      }
    }
  }

  const inspectMaterial = async (source) => {
    if (source !== selectedMaterial) {
      setMaterialInsight(null)
    }
    setSelectedMaterial(source)
    setHasAttemptedRestoreInsight(true)
    await fetchMaterialInsight(source)
  }

  const handleCoverageSourceChange = (source) => {
    if (!source) {
      setSelectedCoverageSource('')
      return
    }
    setSelectedCoverageSource(source)
    if (source !== selectedMaterial) {
      setSelectedMaterial(source)
      setMaterialInsight(null)
    }
  }

  useEffect(() => {
    if (hasAttemptedRestoreInsight || activeTab !== 'retrieval') {
      return
    }

    setHasAttemptedRestoreInsight(true)

    if (!selectedMaterial || materialInsight) {
      return
    }

    fetchMaterialInsight(selectedMaterial, { announce: false })
  }, [activeTab, selectedMaterial, materialInsight, hasAttemptedRestoreInsight])

  const reportFiles = report?.files || []
  const liveFiles = Array.isArray(ingestionStatus?.files) ? ingestionStatus.files : []
  const files = ingestionStatus?.state === 'running' && liveFiles.length > 0 ? liveFiles : reportFiles
  const coverageMaterials = retrievalOverview?.materials || []
  const selectedCoverageMaterial = coverageMaterials.find((item) => item.source === selectedCoverageSource) || null
  const pendingReviewCount = report?.pending_review_files ?? 0
  const materialCount = retrievalOverview?.material_count ?? 0
  const searchableCount = retrievalOverview?.searchable_material_count ?? 0
  const blockedCount = retrievalOverview?.blocked_material_count ?? 0
  const {
    filteredWikiSources,
    filteredWikiEntities,
    filteredWikiAnswers,
    filteredWikiConcepts,
  } = filterWikiPages(wikiIndex, wikiSearchTerm)
  const totalWikiPageCount =
    (wikiIndex?.source_pages?.length || 0)
    + (wikiIndex?.entity_pages?.length || 0)
    + (wikiIndex?.answer_pages?.length || 0)
    + (wikiIndex?.concept_pages?.length || 0)
  const filteredWikiPageCount =
    filteredWikiSources.length
    + filteredWikiEntities.length
    + filteredWikiAnswers.length
    + filteredWikiConcepts.length
  const insightSummarySections = extractStructuredSummarySections(materialInsight?.summary || '')
  const summaryFormatFlags = getSummaryFormatFlags(materialInsight?.summary || '')
  const buildLangsmithTraceUrl = (traceId) => {
    const defaultEndpoint = 'https://api.smith.langchain.com'
    const configuredEndpoint = String(langsmithStatus?.endpoint || defaultEndpoint).trim()
    const project = String(langsmithStatus?.project || 'self-learning-console').trim()

    let appBase = configuredEndpoint
      .replace('://api.smith.langchain.com', '://smith.langchain.com')
      .replace(/\/api\/?$/, '')
      .replace(/\/$/, '')

    if (!/^https?:\/\//.test(appBase)) {
      appBase = 'https://smith.langchain.com'
    }

    const params = new URLSearchParams({
      name: project,
      trace: String(traceId || ''),
    })
    return `${appBase}/projects/p?${params.toString()}`
  }

  useEffect(() => {
    if (!coverageMaterials.length) {
      setSelectedCoverageSource('')
      return
    }

    const exists = coverageMaterials.some((item) => item.source === selectedCoverageSource)
    if (!exists && selectedCoverageSource) {
      setSelectedCoverageSource('')
    }
  }, [coverageMaterials, selectedCoverageSource])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <p className="eyebrow">{text.sidebar.eyebrow}</p>
          <h1>{text.sidebar.title}</h1>
          <p className="sidebar-copy">
            {text.sidebar.tagline}
          </p>
        </div>
        <div className="sidebar-panel">
          <div className="role-switcher" role="tablist" aria-label="Dashboard audience selector">
            <button
              type="button"
              className={`ghost-button role-switcher-button ${isAdminView ? 'role-switcher-button-active' : ''}`}
              onClick={() => switchDashboardMode(DASHBOARD_MODES.admin)}
              aria-pressed={isAdminView}
            >
              {text.roles.admin}
            </button>
            <button
              type="button"
              className={`ghost-button role-switcher-button ${!isAdminView ? 'role-switcher-button-active' : ''}`}
              onClick={() => switchDashboardMode(DASHBOARD_MODES.user)}
              aria-pressed={!isAdminView}
            >
              {text.roles.user}
            </button>
          </div>
          {isAdminView && (
            <button className="primary-button" onClick={triggerReindex}>{text.actions.runReindex}</button>
          )}
          {(() => {
            const isReindexRunning = String(ingestionStatus?.state || '').toLowerCase() === 'running'
            const done = Number(ingestionStatus?.processed_files || 0)
            const total = Number(ingestionStatus?.total_files || 0)
            const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : null
            const liveMsg = isReindexRunning
              ? `Reindex: ${done}${total > 0 ? ` / ${total}` : ''} files${pct !== null ? ` · ${pct}%` : ''}`
              : null
            return (
              <>
                <p className="status-message">{actionMessage || liveMsg || text.actions.noActiveOperations}</p>
                {isReindexRunning && pct !== null && (
                  <div className="progress-bar-track sidebar-progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                    <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                )}
              </>
            )
          })()}
        </div>
      </aside>

      <main className="dashboard-content">

        <section className="tab-bar">
          <button
            className={`tab-button ${activeTab === 'overview' ? 'tab-button-active' : ''}`}
            onClick={() => setActiveTab('overview')}
          >
            <span>{text.tabs.overview}</span>
            <span className="tab-badge">{ready?.status || '...'}</span>
          </button>
          {isAdminView && (
            <button
              className={`tab-button ${activeTab === 'ingestion' ? 'tab-button-active' : ''}`}
              onClick={() => setActiveTab('ingestion')}
            >
              <span>{text.tabs.ingestion}</span>
              <span className="tab-badge">{pendingReviewCount} {text.tabs.pendingSuffix}</span>
            </button>
          )}
          <button
            className={`tab-button ${activeTab === 'retrieval' ? 'tab-button-active' : ''}`}
            onClick={() => setActiveTab('retrieval')}
          >
            <span>{text.tabs.knowledge}</span>
          </button>
          <button
            className={`tab-button ${activeTab === 'knowledge-search' ? 'tab-button-active' : ''}`}
            onClick={() => setActiveTab('knowledge-search')}
          >
            <span>{text.tabs.knowledgeSearch}</span>
            <span className="tab-badge">{retrievalResults?.result_count ?? 0} {text.retrieval.resultsSuffix}</span>
          </button>
          {isAdminView && (
            <button
              className={`tab-button ${activeTab === 'wiki' ? 'tab-button-active' : ''}`}
              onClick={() => setActiveTab('wiki')}
            >
              <span>{text.tabs.wiki}</span>
              <span className="tab-badge">{wikiIndex ? `${totalWikiPageCount}p` : '-'}</span>
            </button>
          )}
        </section>

        {activeTab === 'overview' && (
          <OverviewTab
            text={text}
            ready={ready}
            report={report}
            retrievalOverview={retrievalOverview}
            wikiIndex={wikiIndex}
            warmCacheStatus={warmCacheStatus}
            semanticCacheStats={semanticCacheStats}
            deployIntelStatus={deployIntelStatus}
            langsmithStatus={langsmithStatus}
            evaluationSummary={evaluationSummary}
            formatStageLabel={formatStageLabel}
          />
        )}

        {activeTab === 'ingestion' && (
          <IngestionTab
            text={text}
            loading={loading}
            files={files}
            ingestionStatus={ingestionStatus}
            Badge={Badge}
          />
        )}

        {activeTab === 'retrieval' && (
          <RetrievalTab
            viewMode="insights"
            text={text}
            retrievalToast={retrievalToast}
            showImportantInformation={showImportantInformation}
            toggleImportantInformation={toggleImportantInformation}
            selectedMaterial={selectedMaterial}
            materialInsight={materialInsight}
            materialInsightLoading={materialInsightLoading}
            summaryFormatFlags={summaryFormatFlags}
            insightSummarySections={insightSummarySections}
            retrievalOverview={retrievalOverview}
            searchableCount={searchableCount}
            materialCount={materialCount}
            blockedCount={blockedCount}
            coverageMaterials={coverageMaterials}
            selectedCoverageSource={selectedCoverageSource}
            selectedCoverageMaterial={selectedCoverageMaterial}
            handleCoverageSourceChange={handleCoverageSourceChange}
            inspectMaterial={inspectMaterial}
            Badge={Badge}
            retrievalResults={retrievalResults}
            showKnowledgeSearch={showKnowledgeSearch}
            toggleKnowledgeSearch={toggleKnowledgeSearch}
            retrievalSearch={retrievalSearch}
            setRetrievalSearch={setRetrievalSearch}
            runRetrievalSearch={runRetrievalSearch}
            retrievalLoading={retrievalLoading}
            findMatchingWikiTarget={findMatchingWikiTarget}
            wikiIndex={wikiIndex}
            openWikiSourceFromRetrieval={openWikiSourceFromRetrieval}
            submitRetrievalFeedback={submitRetrievalFeedback}
            feedbackSubmitting={feedbackSubmitting}
            feedbackRecorded={feedbackRecorded}
            fileAnswerToWiki={fileAnswerToWiki}
            answerFiled={answerFiled}
            feedbackSummaryLoading={feedbackSummaryLoading}
            feedbackSummary={feedbackSummary}
            setLightboxImage={setLightboxImage}
            setPdfViewerUrl={setPdfViewerUrl}
            isResultRelevant={isResultRelevant}
            extractQueryKeywords={extractQueryKeywords}
            selectedSuggestedQa={selectedSuggestedQa}
            onSuggestedQuestionSelect={handleSuggestedQuestionSelect}
            isAdmin={isAdminView}
            uiAlignedQaItems={uiAlignedQaItems}
          />
        )}

        {activeTab === 'knowledge-search' && (
          <RetrievalTab
            viewMode="search"
            text={text}
            retrievalToast={retrievalToast}
            showImportantInformation={showImportantInformation}
            toggleImportantInformation={toggleImportantInformation}
            selectedMaterial={selectedMaterial}
            materialInsight={materialInsight}
            materialInsightLoading={materialInsightLoading}
            summaryFormatFlags={summaryFormatFlags}
            insightSummarySections={insightSummarySections}
            retrievalOverview={retrievalOverview}
            searchableCount={searchableCount}
            materialCount={materialCount}
            blockedCount={blockedCount}
            coverageMaterials={coverageMaterials}
            selectedCoverageSource={selectedCoverageSource}
            selectedCoverageMaterial={selectedCoverageMaterial}
            handleCoverageSourceChange={handleCoverageSourceChange}
            inspectMaterial={inspectMaterial}
            Badge={Badge}
            retrievalResults={retrievalResults}
            showKnowledgeSearch={showKnowledgeSearch}
            toggleKnowledgeSearch={toggleKnowledgeSearch}
            retrievalSearch={retrievalSearch}
            setRetrievalSearch={setRetrievalSearch}
            runRetrievalSearch={runRetrievalSearch}
            retrievalLoading={retrievalLoading}
            findMatchingWikiTarget={findMatchingWikiTarget}
            wikiIndex={wikiIndex}
            openWikiSourceFromRetrieval={openWikiSourceFromRetrieval}
            submitRetrievalFeedback={submitRetrievalFeedback}
            feedbackSubmitting={feedbackSubmitting}
            feedbackRecorded={feedbackRecorded}
            fileAnswerToWiki={fileAnswerToWiki}
            answerFiled={answerFiled}
            feedbackSummaryLoading={feedbackSummaryLoading}
            feedbackSummary={feedbackSummary}
            setLightboxImage={setLightboxImage}
            setPdfViewerUrl={setPdfViewerUrl}
            isResultRelevant={isResultRelevant}
            extractQueryKeywords={extractQueryKeywords}
            selectedSuggestedQa={selectedSuggestedQa}
            onSuggestedQuestionSelect={handleSuggestedQuestionSelect}
            isAdmin={isAdminView}
            uiAlignedQaItems={uiAlignedQaItems}
          />
        )}


        {activeTab === 'wiki' && (
          <WikiTab
            text={text}
            wikiLoading={wikiLoading}
            wikiIndex={wikiIndex}
            wikiImpact={wikiImpact}
            wikiImpactFilter={wikiImpactFilter}
            setWikiImpactFilter={setWikiImpactFilter}
            showImpactBucket={showImpactBucket}
            openImpactPage={openImpactPage}
            wikiPage={wikiPage}
            setWikiPage={setWikiPage}
            wikiSearchTerm={wikiSearchTerm}
            setWikiSearchTerm={setWikiSearchTerm}
            filteredWikiPageCount={filteredWikiPageCount}
            totalWikiPageCount={totalWikiPageCount}
            filteredWikiSources={filteredWikiSources}
            filteredWikiEntities={filteredWikiEntities}
            filteredWikiAnswers={filteredWikiAnswers}
            filteredWikiConcepts={filteredWikiConcepts}
            fetchWikiIndex={fetchWikiIndex}
            fetchWikiPage={fetchWikiPage}
            wikiReviewSubmitting={wikiReviewSubmitting}
            updateWikiReviewState={updateWikiReviewState}
            canManageReview={isAdminView}
          />
        )}
      </main>

      {/* Lightbox overlay for chunk page images */}
      {lightboxImage && (
        <div
          className="lightbox-backdrop"
          onClick={() => setLightboxImage(null)}
          role="dialog"
          aria-modal="true"
          aria-label="Page image preview"
        >
          <div className="lightbox-panel" onClick={(e) => e.stopPropagation()}>
            <div className="lightbox-header">
              <span className="lightbox-source">{lightboxImage.source}</span>
              <button
                className="lightbox-close"
                onClick={() => setLightboxImage(null)}
                aria-label="Close preview"
              >
                ✕
              </button>
            </div>
            <div className="lightbox-image-wrap">
              <img src={lightboxImage.url} alt={`Page from ${lightboxImage.source}`} className="lightbox-image" />
            </div>
            {lightboxImage.excerpt && (
              <div className="lightbox-excerpt">{lightboxImage.excerpt}</div>
            )}
          </div>
        </div>
      )}

      {/* PDF viewer overlay */}
      {pdfViewerUrl && (
        <div
          className="pdf-viewer-backdrop"
          onClick={() => setPdfViewerUrl(null)}
          role="dialog"
          aria-modal="true"
          aria-label="PDF document viewer"
        >
          <div className="pdf-viewer-panel" onClick={(e) => e.stopPropagation()}>
            <div className="pdf-viewer-header">
              <span className="pdf-viewer-source">PDF Viewer</span>
              <button
                className="pdf-viewer-close"
                onClick={() => setPdfViewerUrl(null)}
                aria-label="Close PDF viewer"
              >
                ✕
              </button>
            </div>
            <iframe
              src={pdfViewerUrl}
              className="pdf-viewer-iframe"
              title="PDF Document"
              onError={() => {
                const fallbackMsg = document.createElement('div')
                fallbackMsg.style.cssText = 'display:flex;align-items:center;justify-content:center;height:100%;color:#999;'
                fallbackMsg.textContent = 'PDF failed to load. Click to download.'
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}

export default App
