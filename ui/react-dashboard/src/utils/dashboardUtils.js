export const RETRIEVAL_SEARCH_STORAGE_KEY = 'training-agent-dashboard-retrieval-search'

export const normalizeTab = (value) => {
  if (
    value === 'overview'
    || value === 'ingestion'
    || value === 'retrieval'
    || value === 'knowledge-search'
    || value === 'observability'
    || value === 'wiki'
  ) {
    return value
  }
  if (value === 'knowledge') {
    return 'retrieval'
  }
  return null
}

export const readTabFromUrl = () => {
  if (typeof window === 'undefined') {
    return null
  }
  const params = new URLSearchParams(window.location.search)
  return normalizeTab(params.get('tab'))
}

export const readRetrievalSearchFromStorage = () => {
  if (typeof window === 'undefined') {
    return { query: '', domain_context: '' }
  }
  const raw = window.localStorage.getItem(RETRIEVAL_SEARCH_STORAGE_KEY)
  if (!raw) {
    return { query: '', domain_context: '' }
  }
  try {
    const parsed = JSON.parse(raw)
    return {
      query: typeof parsed?.query === 'string' ? parsed.query : '',
      domain_context: typeof parsed?.domain_context === 'string' ? parsed.domain_context : '',
    }
  } catch {
    return { query: '', domain_context: '' }
  }
}

export const readRetrievalSearchFromUrl = () => {
  if (typeof window === 'undefined') {
    return null
  }
  const params = new URLSearchParams(window.location.search)
  const query = params.get('query') || ''
  const domainContext = params.get('domainContext') || params.get('domain_context') || ''
  if (!query && !domainContext) {
    return null
  }
  return {
    query,
    domain_context: domainContext,
  }
}

export const formatStageLabel = (value) => {
  if (!value || typeof value !== 'string') {
    return '-'
  }
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

const STOPWORDS = new Set([
  'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'is', 'are', 'was', 'be',
  'been', 'by', 'with', 'as', 'from', 'about', 'that', 'this', 'which', 'should', 'can', 'what',
  'how', 'when', 'where', 'why', 'who', 'does', 'do', 'did', 'have', 'has', 'having',
])

export const extractQueryKeywords = (query) => {
  if (!query) return []
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter((word) => word.length > 2 && !STOPWORDS.has(word))
    .slice(0, 8)
}

export const isResultRelevant = (result, queryKeywords) => {
  if (!queryKeywords.length) return true
  const text = `${result.source} ${result.excerpt}`.toLowerCase()
  const matchCount = queryKeywords.filter((keyword) => text.includes(keyword)).length
  return matchCount >= Math.max(1, Math.ceil(queryKeywords.length * 0.4))
}

const wikiSlugMatches = (slug, normalizedQuery) => {
  if (!normalizedQuery) {
    return true
  }
  const raw = (slug || '').toLowerCase()
  const humanized = raw.replace(/-/g, ' ')
  return raw.includes(normalizedQuery) || humanized.includes(normalizedQuery)
}

const normalizeWikiLookupKey = (value) =>
  (value || '')
    .toLowerCase()
    .replace(/\.[a-z0-9]{2,5}$/i, '')
    .replace(/[^a-z0-9]+/g, '')

export const normalizeQuestionKey = (value) =>
  (value || '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()

const findMatchingWikiSourceSlug = (source, sourcePages) => {
  if (!source || !Array.isArray(sourcePages) || sourcePages.length === 0) {
    return null
  }

  const raw = String(source)
  const base = raw.split('/').pop() || raw
  const keys = new Set([
    normalizeWikiLookupKey(raw),
    normalizeWikiLookupKey(base),
  ])

  for (const slug of sourcePages) {
    const slugKey = normalizeWikiLookupKey(slug)
    if (!slugKey) {
      continue
    }
    if ([...keys].some((key) => key && key === slugKey)) {
      return slug
    }
  }

  return null
}

export const findMatchingWikiTarget = (source, wikiIndex) => {
  if (!source || !wikiIndex) {
    return null
  }

  const raw = String(source).trim().replace(/^\/+/, '')
  const wikiPathMatch = raw.match(/^wiki\/(sources|entities|concepts|answers)\/([^/]+)\.md$/i)
  if (wikiPathMatch) {
    const folder = wikiPathMatch[1].toLowerCase()
    const slug = wikiPathMatch[2]
    const kindMap = {
      sources: 'source',
      entities: 'entity',
      concepts: 'concept',
      answers: 'answer',
    }
    const kind = kindMap[folder]
    return kind ? { kind, name: slug } : null
  }

  const sourceSlug = findMatchingWikiSourceSlug(source, wikiIndex.source_pages || [])
  if (sourceSlug) {
    return { kind: 'source', name: sourceSlug }
  }

  return null
}

export const extractStructuredSummarySections = (summary) => {
  if (typeof summary !== 'string' || !summary.trim()) {
    return []
  }

  const canonicalHeadingVariants = [
    {
      label: 'Document',
      variants: ['Document:'],
    },
    {
      label: 'Executive Mission',
      variants: ['1. Executive Mission:', 'Executive Mission:', '1. Executive Mission (The Why):', 'Executive Mission (The Why):'],
    },
    {
      label: 'Stakeholder Matrix',
      variants: ['2. Stakeholder Matrix:', 'Stakeholder Matrix:', '2. Stakeholder Matrix (The Who):', 'Stakeholder Matrix (The Who):'],
    },
    {
      label: 'Operational Pillars',
      variants: ['3. Operational Pillars:', 'Operational Pillars:', '3. Operational Pillars (The What):', 'Operational Pillars (The What):'],
    },
    {
      label: 'Execution Roadmap',
      variants: ['4. Execution Roadmap:', 'Execution Roadmap:', '4. Execution Roadmap (The How):', 'Execution Roadmap (The How):'],
    },
    {
      label: 'Critical Safety & Risk Gates',
      variants: [
        '5. Critical Safety & Risk Gates:',
        'Critical Safety & Risk Gates:',
        '5. Critical Safety & Risk Gates (The Watch Out):',
        'Critical Safety & Risk Gates (The Watch Out):',
      ],
    },
    {
      label: 'Lifecycle Triggers',
      variants: ['6. Lifecycle Triggers:', 'Lifecycle Triggers:', '6. Lifecycle Triggers (The When):', 'Lifecycle Triggers (The When):'],
    },
  ]

  const headingVariants = [
    { label: 'Core Thesis', variants: ['Core Thesis:'] },
    {
      label: 'What is this document about?',
      variants: ['What is this document about?:', 'What is this document about?', 'What:'],
    },
    {
      label: 'Why is this process important?',
      variants: ['Why is this process important?:', 'Why is this process important?', 'Why:'],
    },
    {
      label: 'Who should use this document?',
      variants: ['Who should use this document?:', 'Who should use this document?', 'Who:'],
    },
    {
      label: 'How is maintenance performed?',
      variants: ['How is maintenance performed?:', 'How is maintenance performed?', 'How:'],
    },
    {
      label: 'Where is this process performed?',
      variants: ['Where is this process performed?:', 'Where is this process performed?', 'Where:'],
    },
    {
      label: 'When should this process be used?',
      variants: ['When should this process be used?:', 'When should this process be used?', 'When:'],
    },
    {
      label: 'Which modules are covered?',
      variants: ['Which modules are covered?:', 'Which modules are covered?', 'Which:'],
    },
    { label: 'Key Pillars', variants: ['Key Pillars:'] },
    { label: 'Data & Evidence', variants: ['Data & Evidence:'] },
    { label: 'Exceptions / What If', variants: ['Exceptions / What If:'] },
    {
      label: 'Action Items / Conclusions',
      variants: ['Action Items / Conclusions:', 'Action Items/Conclusions:'],
    },
  ]

  const allHeadingVariants = [...canonicalHeadingVariants, ...headingVariants]

  const markers = allHeadingVariants
    .map((entry) => {
      const variantMatches = entry.variants
        .map((variant) => ({ variant, index: summary.indexOf(variant) }))
        .filter((match) => match.index !== -1)
      if (variantMatches.length === 0) {
        return null
      }
      const earliest = variantMatches.reduce((best, current) =>
        current.index < best.index ? current : best,
      )
      return {
        label: entry.label,
        variant: earliest.variant,
        index: earliest.index,
      }
    })
    .filter(Boolean)

  if (markers.length === 0) {
    return []
  }

  const markersByPosition = [...markers].sort((left, right) => left.index - right.index)
  const extractedByLabel = new Map()

  markersByPosition.forEach((marker, index) => {
    const bodyStart = marker.index + marker.variant.length
    const bodyEnd = index + 1 < markersByPosition.length ? markersByPosition[index + 1].index : summary.length
    const body = summary.slice(bodyStart, bodyEnd).trim()
    if (!body) {
      return
    }
    extractedByLabel.set(marker.label, {
      heading: marker.label,
      body,
    })
  })

  return allHeadingVariants
    .map((entry) => extractedByLabel.get(entry.label))
    .filter(Boolean)
}

export const getSummaryFormatFlags = (summary) => {
  const text = typeof summary === 'string' ? summary : ''
  const hasLegacyHeadings = /\bKey\s+Pillars:|\bAction\s+Items\/Conclusions:/i.test(text)
  const sections = extractStructuredSummarySections(text)
  const hasCanonicalKnowledgeBrief = /\b1\.\s*Executive\s+Mission(?:\s*\(The\s+Why\))?:/i.test(text)
  const expectedCount = hasCanonicalKnowledgeBrief ? 7 : 11
  const isPartialStructured = sections.length > 0 && sections.length < expectedCount
  return { hasLegacyHeadings, isPartialStructured }
}

export const filterWikiPages = (wikiIndex, wikiSearchTerm) => {
  const normalizedWikiQuery = wikiSearchTerm.trim().toLowerCase()
  const filteredWikiSources = (wikiIndex?.source_pages || []).filter((slug) => wikiSlugMatches(slug, normalizedWikiQuery))
  const filteredWikiEntities = (wikiIndex?.entity_pages || []).filter((slug) => wikiSlugMatches(slug, normalizedWikiQuery))
  const filteredWikiAnswers = (wikiIndex?.answer_pages || []).filter((slug) => wikiSlugMatches(slug, normalizedWikiQuery))
  const filteredWikiConcepts = (wikiIndex?.concept_pages || []).filter((slug) => wikiSlugMatches(slug, normalizedWikiQuery))

  return {
    filteredWikiSources,
    filteredWikiEntities,
    filteredWikiAnswers,
    filteredWikiConcepts,
  }
}
