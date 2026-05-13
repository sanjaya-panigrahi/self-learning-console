import { afterEach, describe, expect, it } from 'vitest'

import {
  extractStructuredSummarySections,
  getSummaryFormatFlags,
  normalizeTab,
  readRetrievalSearchFromUrl,
  readTabFromUrl,
} from './App.jsx'

const originalWindow = globalThis.window

afterEach(() => {
  if (originalWindow === undefined) {
    delete globalThis.window
  } else {
    globalThis.window = originalWindow
  }
})

describe('tab parsing helpers', () => {
  it('normalizes legacy and valid tabs', () => {
    expect(normalizeTab('knowledge')).toBe('retrieval')
    expect(normalizeTab('observability')).toBe('observability')
    expect(normalizeTab('invalid')).toBeNull()
  })

  it('reads tab from URL query string', () => {
    globalThis.window = { location: { search: '?tab=observability' } }
    expect(readTabFromUrl()).toBe('observability')
  })
})

describe('retrieval URL parsing', () => {
  it('supports both domainContext and domain_context', () => {
    globalThis.window = {
      location: {
        search: '?query=workflow+rules&domain_context=policy',
      },
    }
    expect(readRetrievalSearchFromUrl()).toEqual({
      query: 'workflow rules',
      domain_context: 'policy',
    })

    globalThis.window = {
      location: {
        search: '?query=hotel&domainContext=transport',
      },
    }
    expect(readRetrievalSearchFromUrl()).toEqual({
      query: 'hotel',
      domain_context: 'transport',
    })
  })
})

describe('summary parsing helpers', () => {
  it('returns sections in knowledge brief heading order', () => {
    const summary = [
      '4. Execution Roadmap: Preparation -> Action -> Verification.',
      'Document: Operations Console v1.9 | Knowledge Brief',
      '1. Executive Mission: Standardize updates and reduce risk.',
    ].join('\n\n')

    const sections = extractStructuredSummarySections(summary)
    expect(sections.map((entry) => entry.heading)).toEqual([
      'Document',
      'Executive Mission',
      'Execution Roadmap',
    ])
  })

  it('handles legacy heading variants and reports format flags', () => {
    const summary = [
      'Core Thesis: Baseline insight.',
      'Key Pillars: Legacy heading is still supported.',
      'Action Items/Conclusions: Legacy slash variant.',
    ].join('\n\n')

    const sections = extractStructuredSummarySections(summary)
    expect(sections.map((entry) => entry.heading)).toEqual([
      'Core Thesis',
      'Key Pillars',
      'Action Items / Conclusions',
    ])

    expect(getSummaryFormatFlags(summary)).toEqual({
      hasLegacyHeadings: true,
      isPartialStructured: true,
    })
  })

  it('treats complete knowledge brief as non-partial structure', () => {
    const summary = [
      'Document: Operations Hub v2.3 | Knowledge Brief',
      '1. Executive Mission: Ensure stable incident handling.',
      '2. Stakeholder Matrix: Role matrix here.',
      '3. Operational Pillars: Discovery, Execution, Governance.',
      '4. Execution Roadmap: Preparation, Targeting, Action, Verification.',
      '5. Critical Safety & Risk Gates: [ ] Dependency Check [ ] Environment Sync [ ] Approval Clarity [ ] Rollback Ready',
      '6. Lifecycle Triggers: Routine, Onboarding, Incident Response.',
    ].join('\n\n')

    expect(getSummaryFormatFlags(summary)).toEqual({
      hasLegacyHeadings: false,
      isPartialStructured: false,
    })
  })
})
